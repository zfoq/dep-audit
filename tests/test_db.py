"""Tests for the junk DB loading, validation, and stdlib_map."""

from dep_audit.db import (
    get_junk_entry,
    list_entries,
    load_junk_db,
    load_stdlib_map,
    validate_all,
    validate_entry,
)


def test_load_stdlib_map_python():
    m = load_stdlib_map("python")
    assert "pytz" in m
    assert m["pytz"]["module"] == "zoneinfo"
    assert m["pytz"]["since"] == "3.9"


def test_load_stdlib_map_npm():
    m = load_stdlib_map("npm")
    assert "node-fetch" in m
    assert m["node-fetch"]["module"] == "fetch"


def test_load_stdlib_map_missing_ecosystem():
    m = load_stdlib_map("nonexistent")
    assert m == {}


def test_load_junk_db_python():
    db = load_junk_db("python")
    assert len(db) > 0
    assert "pytz" in db
    assert db["pytz"]["type"] == "stdlib_backport"
    assert db["pytz"]["confidence"] == 0.95


def test_load_junk_db_missing_ecosystem():
    db = load_junk_db("nonexistent")
    assert db == {}


def test_get_junk_entry_exists():
    entry = get_junk_entry("python", "six")
    assert entry is not None
    assert entry["type"] == "zombie_shim"


def test_get_junk_entry_missing():
    entry = get_junk_entry("python", "nonexistent-package-xyz")
    assert entry is None


def test_validate_entry_valid():
    entry = {
        "name": "test",
        "ecosystem": "python",
        "type": "stdlib_backport",
        "confidence": 0.95,
        "flags": ["some flag"],
        "validated": "2026-03-05",
    }
    errors = validate_entry(entry)
    assert errors == []


def test_validate_entry_missing_fields():
    entry = {"name": "test"}
    errors = validate_entry(entry)
    assert len(errors) > 0
    assert any("missing required field" in e for e in errors)


def test_validate_entry_bad_type():
    entry = {
        "name": "test",
        "ecosystem": "python",
        "type": "invalid_type",
        "confidence": 0.5,
        "flags": ["flag"],
        "validated": "2026-03-05",
    }
    errors = validate_entry(entry)
    assert any("invalid type" in e for e in errors)


def test_validate_entry_bad_confidence():
    entry = {
        "name": "test",
        "ecosystem": "python",
        "type": "deprecated",
        "confidence": 1.5,
        "flags": ["flag"],
        "validated": "2026-03-05",
    }
    errors = validate_entry(entry)
    assert any("confidence" in e for e in errors)


def test_validate_entry_empty_flags():
    entry = {
        "name": "test",
        "ecosystem": "python",
        "type": "deprecated",
        "confidence": 0.5,
        "flags": [],
        "validated": "2026-03-05",
    }
    errors = validate_entry(entry)
    assert any("flags" in e for e in errors)


def test_list_entries_python():
    groups = list_entries("python")
    assert "stdlib_backport" in groups
    assert "zombie_shim" in groups
    assert "deprecated" in groups


def test_validate_all_python():
    """All shipped entries should pass validation."""
    errors, warnings = validate_all("python")
    assert errors == [], f"Validation errors: {errors}"
