"""npm lockfile parsers: package-lock.json, yarn.lock, pnpm-lock.yaml, package.json.

Content-based variants accept strings directly so we can parse lockfiles
fetched from remote repos without writing them to disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dep_audit.lockfiles_pkg._types import Dependency, LockfileResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_package_json_deps(
    package_json_content: str | None,
    include_dev: bool,
) -> tuple[set[str], set[str]]:
    """Extract direct and dev dep names from package.json content.

    Returns (all_direct_names, dev_names).
    """
    if not package_json_content:
        return set(), set()
    data = json.loads(package_json_content)
    direct: set[str] = set()
    dev: set[str] = set()
    for name in data.get("dependencies", {}):
        direct.add(name.lower())
    if include_dev:
        for name in data.get("devDependencies", {}):
            direct.add(name.lower())
            dev.add(name.lower())
    return direct, dev


# ---------------------------------------------------------------------------
# Content-based parsers
# ---------------------------------------------------------------------------


def _parse_package_lock_json_content(
    content: str,
    package_json_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse package-lock.json (v1, v2, v3)."""
    data = json.loads(content)
    direct_names, dev_names = _get_package_json_deps(package_json_content, include_dev)

    deps: list[Dependency] = []
    seen: set[str] = set()

    # V2/V3 format: "packages" key with node_modules paths
    if "packages" in data:
        for key, info in data["packages"].items():
            if not key:  # root entry
                continue
            # Extract package name from path like "node_modules/foo"
            # or "node_modules/@scope/bar" or nested "node_modules/a/node_modules/b"
            parts = key.split("node_modules/")
            name = parts[-1] if parts else key
            if not name:
                continue
            name_lower = name.lower()
            if name_lower in seen:
                continue
            seen.add(name_lower)

            is_dev = info.get("dev", False)
            if is_dev and not include_dev:
                continue

            version = info.get("version", "")
            # Direct if only one level deep and in package.json deps
            is_direct = name_lower in direct_names or (
                key.count("node_modules/") == 1 and not direct_names
            )
            group = "dev" if is_dev else "default"
            deps.append(Dependency(name=name, version=version, is_direct=is_direct, group=group))

    # V1 fallback: "dependencies" key with nested structure
    elif "dependencies" in data:
        _parse_package_lock_v1_deps(
            data["dependencies"], deps, seen, direct_names, dev_names, include_dev,
            is_top_level=True,
        )

    return LockfileResult(ecosystem="npm", deps=deps, source_file=source_label)


def _parse_package_lock_v1_deps(
    dependencies: dict,
    deps: list[Dependency],
    seen: set[str],
    direct_names: set[str],
    dev_names: set[str],
    include_dev: bool,
    is_top_level: bool,
) -> None:
    """Recursively parse v1 package-lock.json dependencies."""
    for name, info in dependencies.items():
        name_lower = name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)

        is_dev = info.get("dev", False)
        if is_dev and not include_dev:
            continue

        version = info.get("version", "")
        is_direct = is_top_level and (name_lower in direct_names or not direct_names)
        group = "dev" if is_dev else "default"
        deps.append(Dependency(name=name, version=version, is_direct=is_direct, group=group))

        # Recurse into nested dependencies
        if "dependencies" in info:
            _parse_package_lock_v1_deps(
                info["dependencies"], deps, seen, direct_names, dev_names,
                include_dev, is_top_level=False,
            )


def _parse_yarn_lock_content(
    content: str,
    package_json_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse yarn.lock v1 format.

    Yarn v1 uses a custom format (not JSON/TOML):
        "name@version":
          version "X.Y.Z"
    """
    direct_names, dev_names = _get_package_json_deps(package_json_content, include_dev)

    # Regex for package header line: "name@version": or name@version:
    header_re = re.compile(r'^"?(@?[^@"\s]+)@[^":\s]+[^:]*:')
    version_re = re.compile(r'^\s+version\s+"([^"]+)"')

    deps: list[Dependency] = []
    seen: set[str] = set()

    current_name: str | None = None
    for line in content.splitlines():
        # Skip comments
        if line.startswith("#"):
            continue

        m = header_re.match(line)
        if m:
            current_name = m.group(1)
            continue

        if current_name is not None:
            vm = version_re.match(line)
            if vm:
                name_lower = current_name.lower()
                if name_lower not in seen:
                    seen.add(name_lower)
                    version = vm.group(1)
                    is_direct = name_lower in direct_names or not direct_names
                    is_dev_only = name_lower in dev_names and name_lower not in (
                        direct_names - dev_names
                    )
                    group = "dev" if is_dev_only else "default"
                    deps.append(Dependency(
                        name=current_name, version=version,
                        is_direct=is_direct, group=group,
                    ))
                current_name = None

    if not include_dev:
        deps = [d for d in deps if d.group != "dev"]

    return LockfileResult(ecosystem="npm", deps=deps, source_file=source_label)


def _parse_pnpm_lock_yaml_content(
    content: str,
    package_json_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse pnpm-lock.yaml using line-based extraction (no YAML library needed).

    Handles both pnpm v6 format (/@scope/name@version) and v9+ format (name@version).

    WARNING: This is a regex-based line parser, not a proper YAML parser.
    It may break on unusual pnpm-lock.yaml layouts or future format changes.
    If pnpm parsing issues arise, consider adding a pyyaml optional dependency.
    """
    direct_names, dev_names = _get_package_json_deps(package_json_content, include_dev)

    # Pattern for package entries in the packages section:
    # pnpm v6: /@scope/name@version:  or  /name@version:
    # pnpm v9: @scope/name@version:   or  name@version:
    pkg_re = re.compile(
        r"^\s{2,4}'?/?(@[^@/]+/[^@(:']+|[^@/:('+\s]+)@([^:('+\s]+)"
    )

    deps: list[Dependency] = []
    seen: set[str] = set()
    in_packages = False
    current_name: str | None = None
    current_version: str | None = None
    current_is_dev = False

    for line in content.splitlines():
        stripped = line.rstrip()

        # Detect packages section
        if stripped == "packages:" or stripped == "snapshots:":
            in_packages = stripped == "packages:"
            continue

        # Detect top-level key (end of packages section)
        if in_packages and stripped and not stripped[0].isspace() and stripped.endswith(":"):
            in_packages = False

        if not in_packages:
            continue

        m = pkg_re.match(stripped)
        if m:
            # Flush previous entry
            if current_name is not None:
                _flush_pnpm_entry(
                    current_name, current_version or "", current_is_dev,
                    deps, seen, direct_names, dev_names, include_dev,
                )
            current_name = m.group(1)
            current_version = m.group(2)
            current_is_dev = False
            continue

        # Check for dev marker under current entry
        if current_name is not None and "dev: true" in stripped:
            current_is_dev = True

    # Flush last entry
    if current_name is not None:
        _flush_pnpm_entry(
            current_name, current_version or "", current_is_dev,
            deps, seen, direct_names, dev_names, include_dev,
        )

    return LockfileResult(ecosystem="npm", deps=deps, source_file=source_label)


def _flush_pnpm_entry(
    name: str,
    version: str,
    is_dev: bool,
    deps: list[Dependency],
    seen: set[str],
    direct_names: set[str],
    dev_names: set[str],
    include_dev: bool,
) -> None:
    """Add a pnpm entry to the deps list if not already seen."""
    name_lower = name.lower()
    if name_lower in seen:
        return
    if is_dev and not include_dev:
        return
    seen.add(name_lower)
    is_direct = name_lower in direct_names or not direct_names
    group = "dev" if is_dev else "default"
    deps.append(Dependency(name=name, version=version, is_direct=is_direct, group=group))


def _parse_package_json_content(
    content: str,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse package.json as fallback — direct deps only, versions are ranges."""
    data = json.loads(content)
    deps: list[Dependency] = []

    for name, version_range in data.get("dependencies", {}).items():
        # Strip semver prefixes like ^, ~, >=
        version = re.sub(r"^[\^~>=<]+\s*", "", version_range)
        deps.append(Dependency(name=name, version=version, is_direct=True, group="default"))

    if include_dev:
        for name, version_range in data.get("devDependencies", {}).items():
            version = re.sub(r"^[\^~>=<]+\s*", "", version_range)
            deps.append(Dependency(name=name, version=version, is_direct=True, group="dev"))

    return LockfileResult(ecosystem="npm", deps=deps, source_file=source_label)


# ---------------------------------------------------------------------------
# Path-based parser
# ---------------------------------------------------------------------------


def parse_npm(project_root: Path, include_dev: bool = False) -> LockfileResult:
    """Parse npm lockfiles in priority order."""
    pkg_json = project_root / "package.json"
    pkg_json_content = pkg_json.read_text(encoding="utf-8") if pkg_json.exists() else None

    package_lock = project_root / "package-lock.json"
    if package_lock.exists():
        content = package_lock.read_text(encoding="utf-8")
        return _parse_package_lock_json_content(
            content, pkg_json_content, include_dev, str(package_lock),
        )

    yarn_lock = project_root / "yarn.lock"
    if yarn_lock.exists():
        content = yarn_lock.read_text(encoding="utf-8")
        return _parse_yarn_lock_content(
            content, pkg_json_content, include_dev, str(yarn_lock),
        )

    pnpm_lock = project_root / "pnpm-lock.yaml"
    if pnpm_lock.exists():
        content = pnpm_lock.read_text(encoding="utf-8")
        return _parse_pnpm_lock_yaml_content(
            content, pkg_json_content, include_dev, str(pnpm_lock),
        )

    if pkg_json.exists() and pkg_json_content:
        return _parse_package_json_content(pkg_json_content, include_dev, str(pkg_json))

    return LockfileResult(ecosystem="npm")


def _parse_npm_from_content(
    file_bundle: dict[str, str],
    include_dev: bool,
) -> LockfileResult:
    """Parse npm lockfiles from a content bundle, same priority as parse_npm."""
    pkg_json_content = file_bundle.get("package.json")

    if "package-lock.json" in file_bundle:
        return _parse_package_lock_json_content(
            file_bundle["package-lock.json"],
            pkg_json_content,
            include_dev,
            source_label="package-lock.json (remote)",
        )
    if "yarn.lock" in file_bundle:
        return _parse_yarn_lock_content(
            file_bundle["yarn.lock"],
            pkg_json_content,
            include_dev,
            source_label="yarn.lock (remote)",
        )
    if "pnpm-lock.yaml" in file_bundle:
        return _parse_pnpm_lock_yaml_content(
            file_bundle["pnpm-lock.yaml"],
            pkg_json_content,
            include_dev,
            source_label="pnpm-lock.yaml (remote)",
        )
    if pkg_json_content:
        return _parse_package_json_content(
            pkg_json_content,
            include_dev,
            source_label="package.json (remote)",
        )
    return LockfileResult(ecosystem="npm")
