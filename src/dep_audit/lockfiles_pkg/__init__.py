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

# Re-export types
from dep_audit.lockfiles_pkg._types import Dependency, LockfileResult
from dep_audit.lockfiles_pkg._util import normalize_package_name

# Re-export Cargo parsers
from dep_audit.lockfiles_pkg.cargo import (
    _parse_cargo_lock_content,
    _parse_cargo_toml_content,
    parse_cargo,
)

# Re-export npm parsers
from dep_audit.lockfiles_pkg.npm import (
    _parse_package_json_content,
    _parse_package_lock_json_content,
    _parse_pnpm_lock_yaml_content,
    _parse_yarn_lock_content,
    parse_npm,
)

# Re-export Python parsers
from dep_audit.lockfiles_pkg.python import (
    _parse_poetry_lock_content,
    _parse_pyproject_deps,
    _parse_pyproject_deps_content,
    _parse_requirements_txt,
    _parse_requirements_txt_content,
    _parse_uv_lock_content,
    parse_python,
)

__all__ = [
    "Dependency",
    "LockfileResult",
    "normalize_package_name",
    "parse",
    "parse_from_content",
    "parse_cargo",
    "parse_npm",
    "parse_python",
    # Content parsers (used by tests)
    "_parse_cargo_lock_content",
    "_parse_cargo_toml_content",
    "_parse_package_json_content",
    "_parse_package_lock_json_content",
    "_parse_pnpm_lock_yaml_content",
    "_parse_yarn_lock_content",
    "_parse_poetry_lock_content",
    "_parse_pyproject_deps",
    "_parse_pyproject_deps_content",
    "_parse_requirements_txt",
    "_parse_requirements_txt_content",
    "_parse_uv_lock_content",
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
