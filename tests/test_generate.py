"""Tests for the generate (discovery) pipeline."""

from __future__ import annotations

import datetime

from dep_audit.classify import Classification
from dep_audit.generate import (
    discover_new,
    format_toml_entry,
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
