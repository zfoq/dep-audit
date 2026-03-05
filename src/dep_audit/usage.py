"""Source code import scanning using the ast module.

We parse every .py file in the project and look for import statements that
match the packages we care about. This catches `import X`, `from X import Y`,
and `from X.sub import Z` — but not dynamic imports via importlib (acceptable miss).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_EXCLUDE = {
    "venv", ".venv", "__pycache__", "node_modules",
    ".git", ".tox", ".mypy_cache", ".nox", ".eggs",
    "build", "dist", ".egg-info",
}


@dataclass
class FileRef:
    path: str
    line: int
    symbol: str = ""


@dataclass
class UsageReport:
    import_count: int = 0
    file_count: int = 0
    files: list[FileRef] = field(default_factory=list)


def scan_python_imports(
    source_root: Path,
    package_names: set[str],
    exclude_dirs: set[str] | None = None,
) -> dict[str, UsageReport]:
    """Walk .py files, parse with ast, find import statements matching package names."""
    if exclude_dirs is None:
        exclude_dirs = _DEFAULT_EXCLUDE

    # PyPI uses hyphens (e.g. "my-package") but Python imports use underscores
    # ("my_package"). We need to handle both directions.
    name_to_import = {}
    for name in package_names:
        import_name = name.replace("-", "_")
        name_to_import[import_name.lower()] = name

    results: dict[str, UsageReport] = {name: UsageReport() for name in package_names}
    seen_files: dict[str, set[str]] = {name: set() for name in package_names}

    for py_file in _walk_python_files(source_root, exclude_dirs):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel_path = str(py_file.relative_to(source_root))

        for node in ast.walk(tree):
            matched = _match_import(node, name_to_import)
            if matched is None:
                continue
            pkg_name, symbol = matched
            report = results[pkg_name]
            report.import_count += 1
            report.files.append(FileRef(
                path=rel_path,
                line=getattr(node, "lineno", 0),
                symbol=symbol,
            ))
            seen_files[pkg_name].add(rel_path)

    for name in package_names:
        results[name].file_count = len(seen_files[name])

    return results


def _walk_python_files(root: Path, exclude_dirs: set[str]):
    """Yield .py files under root, skipping excluded directories."""
    if not root.is_dir():
        return
    for item in root.iterdir():
        if item.is_dir():
            if item.name in exclude_dirs or item.name.endswith(".egg-info"):
                continue
            yield from _walk_python_files(item, exclude_dirs)
        elif item.suffix == ".py":
            yield item


def _match_import(
    node: ast.AST,
    name_to_import: dict[str, str],
) -> tuple[str, str] | None:
    """Check if an AST node is an import matching one of our packages.
    Returns (original_package_name, imported_symbol) or None."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0].lower()
            if top in name_to_import:
                return name_to_import[top], alias.name
    elif isinstance(node, ast.ImportFrom) and node.module:
        top = node.module.split(".")[0].lower()
        if top in name_to_import:
            symbols = ", ".join(a.name for a in (node.names or []))
            return name_to_import[top], f"{node.module}.{symbols}" if symbols else node.module
    return None
