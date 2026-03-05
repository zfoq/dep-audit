"""Tests for anchor tracing."""

from dep_audit.anchors import classify_anchor, trace_anchors
from dep_audit.usage import UsageReport


def test_classify_anchor_unused():
    usage = {"my-dep": UsageReport(import_count=0)}
    assert classify_anchor("my-dep", {}, usage) == "UNUSED"


def test_classify_anchor_replaceable():
    usage = {"my-dep": UsageReport(import_count=5)}
    junk_db = {"my-dep": {"type": "stdlib_backport"}}
    assert classify_anchor("my-dep", junk_db, usage) == "REPLACEABLE"


def test_classify_anchor_overkill():
    usage = {"my-dep": UsageReport(import_count=2)}
    assert classify_anchor("my-dep", {}, usage) == "OVERKILL"


def test_classify_anchor_justified():
    usage = {"my-dep": UsageReport(import_count=15)}
    assert classify_anchor("my-dep", {}, usage) == "JUSTIFIED"


def test_classify_anchor_missing_usage():
    """A package not in usage data should be treated as unused."""
    assert classify_anchor("unknown", {}, {}) == "UNUSED"


def test_trace_anchors_direct_dep():
    """A flagged direct dep is its own anchor."""
    tree = {"my-dep": ["sub-dep"], "sub-dep": []}
    usage = {"my-dep": UsageReport(import_count=0)}
    result = trace_anchors(tree, ["my-dep"], {"my-dep"}, {}, usage)
    assert "my-dep" in result
    assert result["my-dep"].anchor_name == "my-dep"
    assert result["my-dep"].anchor_verdict == "UNUSED"


def test_trace_anchors_transitive():
    """A flagged transitive dep should trace back to its direct ancestor."""
    tree = {"requests": ["urllib3", "six"], "urllib3": [], "six": []}
    direct = {"requests"}
    usage = {"requests": UsageReport(import_count=5)}
    result = trace_anchors(tree, ["six"], direct, {}, usage)
    assert "six" in result
    assert result["six"].anchor_name == "requests"
    assert result["six"].anchor_verdict == "JUSTIFIED"
