"""Tests for the junk DB loading."""

from dep_audit.db import (
    get_junk_entry,
    list_entries,
    load_junk_db,
)


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


def test_list_entries_python():
    groups = list_entries("python")
    assert "stdlib_backport" in groups
    assert "zombie_shim" in groups
    assert "deprecated" in groups
