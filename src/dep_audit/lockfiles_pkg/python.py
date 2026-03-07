"""Python lockfile parsers: uv.lock, poetry.lock, pyproject.toml, requirements.txt.

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


def _parse_uv_lock_content(
    lock_content: str,
    pyproject_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse uv.lock from string content."""
    data = tomllib.loads(lock_content)

    # Figure out which packages are direct from pyproject.toml
    direct_deps: set[str] = set()
    dev_groups: set[str] = set()
    if pyproject_content is not None:
        proj = tomllib.loads(pyproject_content)
        for dep_str in proj.get("project", {}).get("dependencies", []):
            name = normalize_package_name(re.split(r"[<>=!~\[;]", dep_str)[0].strip())
            direct_deps.add(name)
        for group_name in proj.get("dependency-groups", {}):
            if group_name != "default":
                dev_groups.add(group_name)
                if include_dev:
                    for dep_str in proj.get("dependency-groups", {}).get(group_name, []):
                        if isinstance(dep_str, str):
                            name = normalize_package_name(re.split(r"[<>=!~\[;]", dep_str)[0].strip())
                            direct_deps.add(name)

    deps: list[Dependency] = []
    for package in data.get("package", []):
        name = normalize_package_name(package.get("name", ""))
        version = package.get("version", "")
        if not name or not version:
            continue

        # Skip the project itself
        source = package.get("source", {})
        if source.get("editable") or source.get("virtual"):
            continue

        is_direct = name in direct_deps
        group = "default"
        dev_marker = package.get("dev", "")
        if dev_marker:
            group = "dev"
            if not include_dev:
                continue

        deps.append(Dependency(name=name, version=version, is_direct=is_direct, group=group))

    return LockfileResult(ecosystem="python", deps=deps, source_file=source_label)


def _parse_poetry_lock_content(
    lock_content: str,
    pyproject_content: str | None,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse poetry.lock from string content."""
    data = tomllib.loads(lock_content)

    direct_deps: set[str] = set()
    if pyproject_content is not None:
        proj = tomllib.loads(pyproject_content)
        for dep_name in proj.get("tool", {}).get("poetry", {}).get("dependencies", {}):
            if dep_name.lower() != "python":
                direct_deps.add(normalize_package_name(dep_name))
        if include_dev:
            for dep_name in proj.get("tool", {}).get("poetry", {}).get("dev-dependencies", {}):
                direct_deps.add(normalize_package_name(dep_name))
            for group_data in proj.get("tool", {}).get("poetry", {}).get("group", {}).values():
                for dep_name in group_data.get("dependencies", {}):
                    direct_deps.add(normalize_package_name(dep_name))

    deps: list[Dependency] = []
    for package in data.get("package", []):
        name = normalize_package_name(package.get("name", ""))
        version = package.get("version", "")
        if not name or not version:
            continue

        category = package.get("category", "main")
        if category != "main" and not include_dev:
            continue

        is_direct = name in direct_deps
        group = "dev" if category != "main" else "default"
        deps.append(Dependency(name=name, version=version, is_direct=is_direct, group=group))

    return LockfileResult(ecosystem="python", deps=deps, source_file=source_label)


def _parse_pyproject_deps_content(
    pyproject_content: str,
    include_dev: bool,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse dependency names from pyproject.toml content (no versions resolved)."""
    data = tomllib.loads(pyproject_content)

    deps: list[Dependency] = []

    for dep_str in data.get("project", {}).get("dependencies", []):
        name = normalize_package_name(re.split(r"[<>=!~\[;]", dep_str)[0].strip())
        version_match = re.search(r"[<>=!~]+\s*([\d.]+)", dep_str)
        version = version_match.group(1) if version_match else ""
        if name:
            deps.append(Dependency(name=name, version=version, is_direct=True, group="default"))

    if include_dev:
        for group_name, group_deps in data.get("dependency-groups", {}).items():
            for dep_str in group_deps:
                if isinstance(dep_str, str):
                    name = normalize_package_name(re.split(r"[<>=!~\[;]", dep_str)[0].strip())
                    version_match = re.search(r"[<>=!~]+\s*([\d.]+)", dep_str)
                    version = version_match.group(1) if version_match else ""
                    if name:
                        deps.append(Dependency(name=name, version=version, is_direct=True, group=group_name))

        for group_name, group_deps in data.get("project", {}).get("optional-dependencies", {}).items():
            for dep_str in group_deps:
                name = normalize_package_name(re.split(r"[<>=!~\[;]", dep_str)[0].strip())
                version_match = re.search(r"[<>=!~]+\s*([\d.]+)", dep_str)
                version = version_match.group(1) if version_match else ""
                if name:
                    deps.append(Dependency(name=name, version=version, is_direct=True, group=group_name))

    return LockfileResult(ecosystem="python", deps=deps, source_file=source_label)


def _parse_requirements_txt_content(
    content: str,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse requirements.txt from string content.

    Lines annotated with ``# dep-audit: ignore`` are recorded in
    ``LockfileResult.inline_ignores`` so the scanner can suppress them.
    """
    deps: list[Dependency] = []
    inline_ignores: set[str] = set()

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        ignored = "# dep-audit: ignore" in line
        code_part = line.split("#")[0].strip()
        parts = re.split(r"[<>=!~\[;@]", code_part)
        name = normalize_package_name(parts[0].strip())
        version_match = re.search(r"==\s*([\d.]+)", code_part)
        version = version_match.group(1) if version_match else ""
        if name:
            deps.append(Dependency(name=name, version=version, is_direct=True, group="default"))
            if ignored:
                inline_ignores.add(name)

    return LockfileResult(ecosystem="python", deps=deps, source_file=source_label, inline_ignores=inline_ignores)


# ---------------------------------------------------------------------------
# Path-based parsers (read from disk, delegate to content parsers)
# ---------------------------------------------------------------------------


def parse_python(project_root: Path, include_dev: bool = False) -> LockfileResult:
    """Parse Python lockfiles in priority order."""
    uv_lock = project_root / "uv.lock"
    if uv_lock.exists():
        return _parse_uv_lock(uv_lock, project_root, include_dev)

    poetry_lock = project_root / "poetry.lock"
    if poetry_lock.exists():
        return _parse_poetry_lock(poetry_lock, project_root, include_dev)

    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        result = _parse_pyproject_deps(pyproject, include_dev)
        if result.deps:
            return result

    req_txt = project_root / "requirements.txt"
    if req_txt.exists():
        return _parse_requirements_txt(req_txt)

    return LockfileResult(ecosystem="python")


def _parse_uv_lock(lock_path: Path, project_root: Path, include_dev: bool) -> LockfileResult:
    """Parse uv.lock from filesystem."""
    lock_content = lock_path.read_text(encoding="utf-8")
    pyproject = project_root / "pyproject.toml"
    pyproject_content = pyproject.read_text(encoding="utf-8") if pyproject.exists() else None
    return _parse_uv_lock_content(lock_content, pyproject_content, include_dev, str(lock_path))


def _parse_poetry_lock(lock_path: Path, project_root: Path, include_dev: bool) -> LockfileResult:
    """Parse poetry.lock from filesystem."""
    lock_content = lock_path.read_text(encoding="utf-8")
    pyproject = lock_path.parent / "pyproject.toml"
    pyproject_content = pyproject.read_text(encoding="utf-8") if pyproject.exists() else None
    return _parse_poetry_lock_content(lock_content, pyproject_content, include_dev, str(lock_path))


def _parse_pyproject_deps(pyproject_path: Path, include_dev: bool) -> LockfileResult:
    """Parse pyproject.toml from filesystem."""
    content = pyproject_path.read_text(encoding="utf-8")
    return _parse_pyproject_deps_content(content, include_dev, str(pyproject_path))


def _parse_requirements_txt(req_path: Path) -> LockfileResult:
    """Parse requirements.txt from filesystem."""
    content = req_path.read_text(encoding="utf-8")
    return _parse_requirements_txt_content(content, str(req_path))


def _parse_python_from_content(
    file_bundle: dict[str, str],
    include_dev: bool,
) -> LockfileResult:
    """Parse Python lockfiles from a content bundle, same priority as parse_python."""
    if "uv.lock" in file_bundle:
        return _parse_uv_lock_content(
            file_bundle["uv.lock"],
            file_bundle.get("pyproject.toml"),
            include_dev,
            source_label="uv.lock (remote)",
        )
    if "poetry.lock" in file_bundle:
        return _parse_poetry_lock_content(
            file_bundle["poetry.lock"],
            file_bundle.get("pyproject.toml"),
            include_dev,
            source_label="poetry.lock (remote)",
        )
    if "pyproject.toml" in file_bundle:
        result = _parse_pyproject_deps_content(
            file_bundle["pyproject.toml"],
            include_dev,
            source_label="pyproject.toml (remote)",
        )
        if result.deps:
            return result
    if "requirements.txt" in file_bundle:
        return _parse_requirements_txt_content(
            file_bundle["requirements.txt"],
            source_label="requirements.txt (remote)",
        )
    return LockfileResult(ecosystem="python")
