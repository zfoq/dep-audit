"""Cargo lockfile parsers: Cargo.lock, Cargo.toml.

Content-based variants accept strings directly so we can parse lockfiles
fetched from remote repos without writing them to disk.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from dep_audit.lockfiles_pkg._types import Dependency, LockfileResult
from dep_audit.lockfiles_pkg._util import normalize_package_name

# ---------------------------------------------------------------------------
# Content-based parsers (work on strings, no filesystem access)
# ---------------------------------------------------------------------------


def _parse_cargo_lock_content(
    lock_content: str,
    cargo_toml_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse Cargo.lock from string content.

    Cargo.lock is TOML with [[package]] entries.  Root/workspace packages
    have no ``source`` field — we skip those.  Direct deps are identified
    by cross-referencing Cargo.toml.
    """
    data = tomllib.loads(lock_content)

    # Build set of direct dep names from Cargo.toml
    direct_names, dev_names = _get_cargo_toml_deps(cargo_toml_content)

    deps: list[Dependency] = []
    seen: set[str] = set()
    tree_edges: dict[str, list[str]] = {}

    for package in data.get("package", []):
        name = package.get("name", "")
        version = package.get("version", "")
        source = package.get("source")

        if not name or not version:
            continue

        # Root/workspace packages have no source — skip them
        if source is None:
            # Still record their dependencies for tree_edges
            dep_list = package.get("dependencies", [])
            _record_tree_edges(tree_edges, name, dep_list)
            continue

        norm = normalize_package_name(name)
        if norm in seen:
            continue
        seen.add(norm)

        # Check if this is a dev dependency
        is_dev = norm in dev_names and norm not in direct_names
        if is_dev and not include_dev:
            continue

        is_direct = norm in direct_names or norm in dev_names
        group = "dev" if is_dev else "default"

        deps.append(Dependency(
            name=norm, version=version, is_direct=is_direct, group=group,
        ))

        # Record tree edges
        dep_list = package.get("dependencies", [])
        _record_tree_edges(tree_edges, norm, dep_list)

    return LockfileResult(
        ecosystem="cargo", deps=deps, source_file=source_label,
        tree_edges=tree_edges,
    )


def _record_tree_edges(
    tree_edges: dict[str, list[str]],
    parent: str,
    dep_list: list,
) -> None:
    """Record parent→child edges from Cargo.lock dependencies."""
    children: list[str] = []
    for dep in dep_list:
        if isinstance(dep, str):
            # "serde_derive" or "serde_derive 1.0.193"
            child_name = normalize_package_name(dep.split()[0])
            children.append(child_name)
    tree_edges[normalize_package_name(parent)] = children


def _get_cargo_toml_deps(
    cargo_toml_content: str | None,
) -> tuple[set[str], set[str]]:
    """Extract direct and dev dep names from Cargo.toml content.

    Returns (direct_names, dev_names).
    """
    if not cargo_toml_content:
        return set(), set()

    data = tomllib.loads(cargo_toml_content)

    direct: set[str] = set()
    for name in data.get("dependencies", {}):
        direct.add(normalize_package_name(name))

    dev: set[str] = set()
    for name in data.get("dev-dependencies", {}):
        dev.add(normalize_package_name(name))

    return direct, dev


def _parse_cargo_toml_content(
    content: str,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse Cargo.toml as fallback — direct deps only, versions may be ranges."""
    data = tomllib.loads(content)
    deps: list[Dependency] = []

    for name, spec in data.get("dependencies", {}).items():
        version = _extract_version(spec)
        deps.append(Dependency(
            name=normalize_package_name(name),
            version=version,
            is_direct=True,
            group="default",
        ))

    if include_dev:
        for name, spec in data.get("dev-dependencies", {}).items():
            deps.append(Dependency(
                name=normalize_package_name(name),
                version=_extract_version(spec),
                is_direct=True,
                group="dev",
            ))

    return LockfileResult(ecosystem="cargo", deps=deps, source_file=source_label)


_VERSION_PREFIX = re.compile(r"^[\^~>=<= ]+")


def _extract_version(spec: str | dict) -> str:
    """Extract version string from a Cargo.toml dependency spec.

    Can be a simple string ("1.0") or a table ({version = "1.0", features = [...]}).
    """
    if isinstance(spec, str):
        return _VERSION_PREFIX.sub("", spec)
    if isinstance(spec, dict):
        v = spec.get("version", "")
        if isinstance(v, str):
            return _VERSION_PREFIX.sub("", v)
    return ""


# ---------------------------------------------------------------------------
# Path-based parser
# ---------------------------------------------------------------------------


def parse_cargo(project_root: Path, include_dev: bool = False) -> LockfileResult:
    """Parse Cargo lockfiles in priority order."""
    cargo_toml = project_root / "Cargo.toml"
    cargo_toml_content = cargo_toml.read_text(encoding="utf-8") if cargo_toml.exists() else None

    cargo_lock = project_root / "Cargo.lock"
    if cargo_lock.exists():
        content = cargo_lock.read_text(encoding="utf-8")
        return _parse_cargo_lock_content(
            content, cargo_toml_content, include_dev, str(cargo_lock),
        )

    if cargo_toml.exists() and cargo_toml_content:
        return _parse_cargo_toml_content(cargo_toml_content, include_dev, str(cargo_toml))

    return LockfileResult(ecosystem="cargo")


def _parse_cargo_from_content(
    file_bundle: dict[str, str],
    include_dev: bool,
) -> LockfileResult:
    """Parse Cargo lockfiles from a content bundle, same priority as parse_cargo."""
    cargo_toml_content = file_bundle.get("Cargo.toml")

    if "Cargo.lock" in file_bundle:
        return _parse_cargo_lock_content(
            file_bundle["Cargo.lock"],
            cargo_toml_content,
            include_dev,
            source_label="Cargo.lock (remote)",
        )
    if cargo_toml_content:
        return _parse_cargo_toml_content(
            cargo_toml_content,
            include_dev,
            source_label="Cargo.toml (remote)",
        )
    return LockfileResult(ecosystem="cargo")
