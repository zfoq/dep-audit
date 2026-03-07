"""Load the TOML junk database."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger("dep_audit")

_PACKAGE_DIR = Path(__file__).resolve().parent
_DB_DIR = _PACKAGE_DIR / "db"


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
        except Exception as e:
            logger.warning("Failed to load junk DB entry %s: %s", p.name, e)
            continue
    return entries


def get_entry_path(ecosystem: str, package: str) -> Path:
    """Return the filesystem path for a junk DB entry."""
    return _DB_DIR / ecosystem / f"{package}.toml"


def get_junk_entry(ecosystem: str, package: str) -> dict | None:
    """Load a single junk DB entry for a package.

    First tries the conventional {package}.toml path (works for Python/npm/Cargo).
    Falls back to scanning all entries by name field, which handles Go module paths
    that contain slashes and cannot be represented as a flat filename.
    """
    p = get_entry_path(ecosystem, package)
    if p.exists():
        try:
            with open(p, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            logger.warning("Failed to load junk DB entry %s: %s", p.name, e)
            return None

    # Fallback: search all entries by name (handles Go-style module paths with slashes)
    all_entries = load_junk_db(ecosystem)
    return all_entries.get(package)


def list_entries(ecosystem: str) -> dict[str, list[str]]:
    """Group entries by type. Returns {type: [name, ...]}."""
    junk_db = load_junk_db(ecosystem)
    groups: dict[str, list[str]] = {}
    for name, entry in junk_db.items():
        t = entry.get("type", "unknown")
        groups.setdefault(t, []).append(name)
    return groups


