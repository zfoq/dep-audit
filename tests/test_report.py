"""Tests for report formatting."""

import json

from dep_audit.anchors import AnchorResult
from dep_audit.classify import Classification
from dep_audit.report import anchor_report, json_report, terminal_report
from dep_audit.usage import FileRef, UsageReport


def _make_test_data():
    """Build a small set of classifications and usage data for testing."""
    classifications = [
        Classification(
            name="pytz", version="2024.1", classification="stdlib_backport",
            confidence=0.95, replacement="zoneinfo", stdlib_since="3.9",
            is_direct=True, flags=["stdlib_backport: zoneinfo available since Python 3.9"],
        ),
        Classification(
            name="colorama", version="0.4.6", classification="stdlib_backport",
            confidence=0.95, replacement="", is_direct=True,
        ),
        Classification(
            name="requests", version="2.31.0", classification="ok",
            is_direct=True,
        ),
    ]
    usage = {
        "pytz": UsageReport(import_count=2, file_count=1, files=[
            FileRef(path="src/utils.py", line=5, symbol="pytz.timezone"),
            FileRef(path="src/utils.py", line=12, symbol="pytz.utc"),
        ]),
        "colorama": UsageReport(import_count=0, file_count=0),
        "requests": UsageReport(import_count=10, file_count=5),
    }
    anchors = {
        "pytz": AnchorResult(anchor_name="pytz", anchor_verdict="REPLACEABLE", chain=["pytz"]),
        "colorama": AnchorResult(anchor_name="colorama", anchor_verdict="UNUSED", chain=["colorama"]),
    }
    return classifications, usage, anchors


def test_terminal_report_has_sections():
    classifications, usage, anchors = _make_test_data()
    output = terminal_report("myproject", "python", "3.12", 10, classifications, usage, anchors)
    assert "REMOVE" in output
    assert "REPLACE" in output
    assert "DEPRECATED" in output
    assert "SUMMARY" in output
    assert "colorama" in output  # unused, should appear in REMOVE
    assert "pytz" in output      # stdlib_backport, should appear in REPLACE


def test_terminal_report_unused_section():
    classifications, usage, anchors = _make_test_data()
    output = terminal_report("myproject", "python", "3.12", 10, classifications, usage, anchors)
    # colorama is unused (0 imports) so it should be in the REMOVE section
    remove_idx = output.index("REMOVE")
    replace_idx = output.index("REPLACE")
    colorama_idx = output.index("colorama")
    assert remove_idx < colorama_idx < replace_idx


def test_json_report_valid_json():
    classifications, usage, anchors = _make_test_data()
    output = json_report("myproject", "python", "3.12", 10, classifications, usage, anchors)
    data = json.loads(output)
    assert data["project"] == "myproject"
    assert data["ecosystem"] == "python"
    assert data["target_version"] == "3.12"
    assert "flagged" in data
    assert "summary" in data


def test_json_report_flagged_count():
    classifications, usage, anchors = _make_test_data()
    output = json_report("myproject", "python", "3.12", 10, classifications, usage, anchors)
    data = json.loads(output)
    # Only pytz and colorama are flagged (requests is "ok")
    assert len(data["flagged"]) == 2
    names = {f["name"] for f in data["flagged"]}
    assert names == {"pytz", "colorama"}


def test_anchor_report_groups():
    classifications, usage, anchors = _make_test_data()
    output = anchor_report("myproject", "python", "3.12", classifications, usage, anchors)
    assert "grouped by anchor" in output
    assert "colorama" in output
    assert "pytz" in output


def test_terminal_report_no_flagged():
    """When nothing is flagged, the report should say (none) everywhere."""
    classifications = [
        Classification(name="requests", version="2.31.0", classification="ok", is_direct=True),
    ]
    output = terminal_report("myproject", "python", "3.12", 1, classifications, {}, {})
    assert "(none)" in output
    assert "0 unnecessary" in output
