"""Tests for the generate (discovery) pipeline."""

from __future__ import annotations

import datetime

from dep_audit.classify import Classification
from dep_audit.generate import (
    discover_new,
    export_discovered,
    format_toml_entry,
    write_to_db,
)


def _make_classification(
    name: str,
    classification: str = "stdlib_backport",
    confidence: float = 0.95,
    replacement: str = "tomllib",
    stdlib_since: str = "3.11",
    flags: list[str] | None = None,
) -> Classification:
    return Classification(
        name=name,
        version="1.0.0",
        classification=classification,
        confidence=confidence,
        replacement=replacement,
        stdlib_since=stdlib_since,
        flags=flags or ["stdlib_backport: tomllib available since Python 3.11"],
    )


def test_discover_new_filters_known():
    """Packages in the junk DB should not appear in discover_new results."""
    # pytz IS in the junk DB, so it should be filtered out
    classifications = [
        _make_classification("pytz", replacement="zoneinfo", stdlib_since="3.9"),
        _make_classification("totally-fake-pkg-xyz"),
    ]
    discovered = discover_new(classifications, "python")
    names = [c.name for c in discovered]
    assert "pytz" not in names
    assert "totally-fake-pkg-xyz" in names


def test_discover_new_skips_ok():
    """Packages classified as 'ok' should not be discovered."""
    classifications = [
        Classification(name="requests", version="2.31.0", classification="ok"),
    ]
    discovered = discover_new(classifications, "python")
    assert len(discovered) == 0


def test_format_toml_entry_basic():
    """Generated TOML should have all required fields."""
    c = _make_classification("fake-pkg")
    toml = format_toml_entry(c, "python")
    assert 'name = "fake-pkg"' in toml
    assert 'ecosystem = "python"' in toml
    assert 'type = "stdlib_backport"' in toml
    assert "confidence = 0.95" in toml
    assert 'replacement = "tomllib"' in toml
    assert 'stdlib_since = "3.11"' in toml
    assert "flags = [" in toml
    assert f"validated = {datetime.date.today().isoformat()}" in toml


def test_format_toml_entry_deprecated():
    """Deprecated entries should not have stdlib_since."""
    c = _make_classification(
        "old-pkg",
        classification="deprecated",
        confidence=0.90,
        replacement="new-pkg",
        stdlib_since="",
        flags=["deprecated: flagged by deps.dev"],
    )
    toml = format_toml_entry(c, "python")
    assert 'type = "deprecated"' in toml
    assert 'replacement = "new-pkg"' in toml
    assert "stdlib_since" not in toml


def test_format_toml_entry_escapes_quotes():
    """Quotes in flags should be escaped."""
    c = _make_classification(
        "quotey",
        flags=['use "new_thing" instead'],
    )
    toml = format_toml_entry(c, "python")
    assert 'use \\"new_thing\\" instead' in toml


def test_export_discovered_writes_files(tmp_path):
    """export_discovered should write TOML files to the output dir."""
    classifications = [
        _make_classification("pkg-a"),
        _make_classification("pkg-b", classification="deprecated", replacement="pkg-c"),
    ]
    output_dir = tmp_path / "python"
    written = export_discovered(classifications, "python", output_dir)
    assert len(written) == 2
    assert (output_dir / "pkg-a.toml").exists()
    assert (output_dir / "pkg-b.toml").exists()

    content = (output_dir / "pkg-a.toml").read_text()
    assert 'name = "pkg-a"' in content


def test_export_discovered_skips_ok(tmp_path):
    """ok classifications should not be exported."""
    classifications = [
        Classification(name="fine", version="1.0", classification="ok"),
    ]
    written = export_discovered(classifications, "python", tmp_path / "python")
    assert len(written) == 0


def test_write_to_db_creates_files(tmp_path, monkeypatch):
    """write_to_db should write files to db/{ecosystem}/."""
    import dep_audit.generate as gen
    monkeypatch.setattr(gen, "_DB_DIR", tmp_path / "db")

    classifications = [
        _make_classification("new-discovery"),
    ]
    written = write_to_db(classifications, "python")
    assert len(written) == 1
    assert written[0].name == "new-discovery.toml"
    assert written[0].exists()


def test_write_to_db_skips_existing(tmp_path, monkeypatch):
    """write_to_db should not overwrite existing entries."""
    import dep_audit.generate as gen
    monkeypatch.setattr(gen, "_DB_DIR", tmp_path / "db")

    db_dir = tmp_path / "db" / "python"
    db_dir.mkdir(parents=True)
    (db_dir / "existing.toml").write_text('name = "existing"\n')

    classifications = [
        _make_classification("existing"),
    ]
    written = write_to_db(classifications, "python")
    assert len(written) == 0
    # Verify original content preserved
    assert (db_dir / "existing.toml").read_text() == 'name = "existing"\n'


def test_discover_and_export_roundtrip(tmp_path):
    """Full pipeline: discover_new -> export_discovered."""
    # Mix of known (pytz) and unknown packages
    classifications = [
        _make_classification("pytz", replacement="zoneinfo", stdlib_since="3.9"),
        _make_classification("never-heard-of-this"),
        Classification(name="requests", version="2.31.0", classification="ok"),
    ]

    discovered = discover_new(classifications, "python")
    assert len(discovered) == 1
    assert discovered[0].name == "never-heard-of-this"

    output_dir = tmp_path / "python"
    written = export_discovered(discovered, "python", output_dir)
    assert len(written) == 1
    assert (output_dir / "never-heard-of-this.toml").exists()
