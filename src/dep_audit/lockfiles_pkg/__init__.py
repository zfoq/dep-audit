"""Lockfile parsers per ecosystem.

Each parser extracts a flat list of (name, version, direct?) tuples.
Priority order for Python: uv.lock > poetry.lock > pyproject.toml > requirements.txt
Priority order for npm: package-lock.json > yarn.lock > pnpm-lock.yaml > package.json
Priority order for Cargo: Cargo.lock > Cargo.toml

Content-based variants (_parse_*_content) accept strings directly so we can
parse lockfiles fetched from remote repos without writing them to disk.
"""

from __future__ import annotations

from pathlib import Path

# Re-export public types and parsers
from dep_audit.lockfiles_pkg._types import Dependency, LockfileResult
from dep_audit.lockfiles_pkg._util import normalize_package_name
from dep_audit.lockfiles_pkg.cargo import parse_cargo
from dep_audit.lockfiles_pkg.go import parse_go
from dep_audit.lockfiles_pkg.npm import parse_npm
from dep_audit.lockfiles_pkg.python import parse_python

__all__ = [
    "Dependency",
    "LockfileResult",
    "normalize_package_name",
    "parse",
    "parse_from_content",
    "parse_cargo",
    "parse_go",
    "parse_npm",
    "parse_python",
]


def parse(project_root: Path, ecosystem: str, include_dev: bool = False) -> LockfileResult:
    """Parse lockfile for the given ecosystem (local filesystem)."""
    from dep_audit import ecosystems

    eco = ecosystems.get_or_none(ecosystem)
    if eco is None:
        return LockfileResult(ecosystem=ecosystem)
    return eco.parse(project_root, include_dev)


def parse_from_content(
    ecosystem: str,
    file_bundle: dict[str, str],
    include_dev: bool = False,
) -> LockfileResult:
    """Parse lockfile from a content bundle (for remote scanning).

    file_bundle maps filenames to their text content,
    e.g. {"uv.lock": "...", "pyproject.toml": "..."}.
    """
    from dep_audit import ecosystems

    eco = ecosystems.get_or_none(ecosystem)
    if eco is None:
        return LockfileResult(ecosystem=ecosystem)
    return eco.parse_from_content(file_bundle, include_dev)
