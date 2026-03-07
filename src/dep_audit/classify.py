"""Classification decision tree for packages.

The order matters: junk DB first (curated, high confidence), then deps.dev
deprecated flag (live API check). Anything that doesn't match is "ok".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dep_audit import db, depsdev


@dataclass
class Classification:
    name: str
    version: str
    classification: str  # stdlib_backport, zombie_shim, deprecated, micro_utility, unused, ok
    confidence: float = 0.0
    replacement: str = ""
    stdlib_since: str = ""
    is_direct: bool = True
    flags: list[str] = field(default_factory=list)


def classify_package(
    ecosystem: str,
    name: str,
    version: str,
    target_version: str,
    is_direct: bool,
    junk_db: dict[str, dict],
    offline: bool = False,
) -> Classification:
    """Classify a single package using the decision tree."""

    result = Classification(
        name=name,
        version=version,
        is_direct=is_direct,
        classification="ok",
    )

    # First check: the curated junk DB
    entry = junk_db.get(name)
    if entry is not None:
        stdlib_since = entry.get("stdlib_since", "")
        if stdlib_since and not _version_ge(target_version, stdlib_since):
            # stdlib replacement not available for this target version
            pass
        else:
            result.classification = entry.get("type", "unknown")
            result.replacement = entry.get("replacement", "")
            result.confidence = entry.get("confidence", 0.0)
            result.stdlib_since = stdlib_since
            result.flags = entry.get("flags", [])
            return result

    # Last resort: ask deps.dev if the maintainer marked it deprecated
    if not offline and version:
        deprecated, dep_msg = depsdev.is_deprecated(ecosystem, name, version)
        if deprecated:
            result.classification = "deprecated"
            result.confidence = 0.90
            result.flags = ["deprecated: flagged by deps.dev"]
            result.replacement = _parse_replacement(dep_msg)
            return result

    return result


def classify_all(
    ecosystem: str,
    packages: list[dict[str, Any]],
    target_version: str,
    offline: bool = False,
    junk_db: dict[str, dict] | None = None,
) -> list[Classification]:
    """Classify a list of packages."""
    if junk_db is None:
        junk_db = db.load_junk_db(ecosystem)

    results: list[Classification] = []
    for pkg in packages:
        c = classify_package(
            ecosystem=ecosystem,
            name=pkg["name"],
            version=pkg.get("version", ""),
            target_version=target_version,
            is_direct=pkg.get("is_direct", True),
            junk_db=junk_db,
            offline=offline,
        )
        results.append(c)
    return results


def _version_ge(current: str, required: str) -> bool:
    """Check if current version >= required version (dotted strings)."""
    try:
        cur_parts = [int(x) for x in current.split(".")]
        req_parts = [int(x) for x in required.split(".")]
        return cur_parts >= req_parts
    except (ValueError, AttributeError):
        return False


# Common patterns in deprecation messages — "use X instead", "replaced by X", etc.
_REPLACEMENT_PATTERNS = [
    re.compile(r"use\s+(\S+)\s+instead", re.IGNORECASE),
    re.compile(r"replaced\s+by\s+(\S+)", re.IGNORECASE),
    re.compile(r"switch\s+to\s+(\S+)", re.IGNORECASE),
    re.compile(r"migrate\s+to\s+(\S+)", re.IGNORECASE),
]


def _parse_replacement(message: str) -> str:
    """Try to extract a replacement package name from a deprecation message."""
    for pattern in _REPLACEMENT_PATTERNS:
        m = pattern.search(message)
        if m:
            return m.group(1).strip("`'\".,;:")
    return ""
