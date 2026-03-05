"""Load the TOML junk database and stdlib_map."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_DB_DIR = _PACKAGE_DIR / "db"
_STDLIB_MAP_DIR = _PACKAGE_DIR / "stdlib_map"


def load_stdlib_map(ecosystem: str) -> dict[str, dict]:
    """Load stdlib_map/{ecosystem}.toml and return {pkg_name: {module, since, ...}}."""
    p = _STDLIB_MAP_DIR / f"{ecosystem}.toml"
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def load_junk_db(ecosystem: str) -> dict[str, dict]:
    """Load all TOML entries from db/{ecosystem}/ into {pkg_name: entry}."""
    d = _DB_DIR / ecosystem
    if not d.is_dir():
        return {}
    entries: dict[str, dict] = {}
    for p in sorted(d.glob("*.toml")):
        try:
            with open(p, "rb") as f:
                entry = tomllib.load(f)
            name = entry.get("name", p.stem)
            entries[name] = entry
        except Exception:
            continue
    return entries


def get_junk_entry(ecosystem: str, package: str) -> dict | None:
    """Load a single junk DB entry for a package."""
    p = _DB_DIR / ecosystem / f"{package}.toml"
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def validate_entry(entry: dict) -> list[str]:
    """Validate a junk DB entry. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    required = ["name", "ecosystem", "type", "confidence", "flags", "validated"]
    for field in required:
        if field not in entry:
            errors.append(f"missing required field: {field}")

    valid_types = {"stdlib_backport", "zombie_shim", "deprecated", "micro_utility"}
    if "type" in entry and entry["type"] not in valid_types:
        errors.append(f"invalid type: {entry['type']} (must be one of {valid_types})")

    if "confidence" in entry:
        c = entry["confidence"]
        if not isinstance(c, (int, float)) or not (0.0 <= c <= 1.0):
            errors.append(f"confidence must be 0.0-1.0, got {c}")

    if "flags" in entry and (not isinstance(entry["flags"], list) or len(entry["flags"]) == 0):
        errors.append("flags must be a non-empty list")

    return errors


def list_entries(ecosystem: str) -> dict[str, list[str]]:
    """Group entries by type. Returns {type: [name, ...]}."""
    db = load_junk_db(ecosystem)
    groups: dict[str, list[str]] = {}
    for name, entry in db.items():
        t = entry.get("type", "unknown")
        groups.setdefault(t, []).append(name)
    return groups


def validate_all(ecosystem: str) -> tuple[list[str], list[str]]:
    """Validate all entries. Returns (errors, warnings)."""
    import datetime

    errors: list[str] = []
    warnings: list[str] = []
    d = _DB_DIR / ecosystem
    if not d.is_dir():
        errors.append(f"directory not found: {d}")
        return errors, warnings

    for p in sorted(d.glob("*.toml")):
        try:
            with open(p, "rb") as f:
                entry = tomllib.load(f)
        except Exception as e:
            errors.append(f"{p.name}: TOML parse error: {e}")
            continue

        for err in validate_entry(entry):
            errors.append(f"{p.name}: {err}")

        # Check staleness
        validated = entry.get("validated")
        if validated:
            try:
                if isinstance(validated, datetime.date):
                    vdate = validated
                else:
                    vdate = datetime.date.fromisoformat(str(validated))
                age = (datetime.date.today() - vdate).days
                if age > 365:
                    warnings.append(f"{p.name}: validated date is {age} days old")
            except (ValueError, TypeError):
                warnings.append(f"{p.name}: could not parse validated date")

    return errors, warnings
