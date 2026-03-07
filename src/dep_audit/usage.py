"""Source code import scanning.

Python: We parse every .py file using the ast module and look for import
statements matching the packages we care about.

JavaScript: We use regex patterns to detect require(), import/export from,
and dynamic import() across .js/.ts/.jsx/.tsx/.mjs/.cjs files.

Rust: We use regex patterns to detect use/extern crate statements
across .rs files.
"""

from __future__ import annotations

import ast
import re
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
    """Yield .py files under root, skipping excluded directories.

    Uses Path.rglob instead of manual recursion to avoid hitting
    Python's recursion limit on deeply nested projects.
    """
    if not root.is_dir():
        return
    for item in root.rglob("*.py"):
        if any(p in exclude_dirs or p.endswith(".egg-info") for p in item.relative_to(root).parts[:-1]):
            continue
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


# ---------------------------------------------------------------------------
# JavaScript / TypeScript import scanning
# ---------------------------------------------------------------------------

_JS_EXCLUDE = {
    "node_modules", ".git", "dist", "build", ".next", ".nuxt",
    "coverage", ".cache", "__pycache__", ".turbo", "out",
}

_JS_EXTENSIONS = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}

# Matches: require("pkg"), require('pkg')
_RE_REQUIRE = re.compile(r"""require\(\s*["']([^"']+)["']\s*\)""")

# Matches: import ... from "pkg", import "pkg", export ... from "pkg"
_RE_IMPORT_FROM = re.compile(
    r"""(?:import|export)\s+(?:.*?\s+from\s+)?["']([^"']+)["']"""
)

# Matches: import("pkg") — dynamic import
_RE_DYNAMIC_IMPORT = re.compile(r"""import\(\s*["']([^"']+)["']\s*\)""")


def scan_javascript_imports(
    source_root: Path,
    package_names: set[str],
    exclude_dirs: set[str] | None = None,
) -> dict[str, UsageReport]:
    """Walk JS/TS files, find require/import/export statements matching package names."""
    if exclude_dirs is None:
        exclude_dirs = _JS_EXCLUDE

    # npm package names map directly to import specifiers (no transformation needed)
    name_lookup: dict[str, str] = {}
    for name in package_names:
        name_lookup[name.lower()] = name

    results: dict[str, UsageReport] = {name: UsageReport() for name in package_names}
    seen_files: dict[str, set[str]] = {name: set() for name in package_names}

    for js_file in _walk_javascript_files(source_root, exclude_dirs):
        try:
            source = js_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = str(js_file.relative_to(source_root))

        for line_no, line in enumerate(source.splitlines(), 1):
            for specifier in _extract_js_specifiers(line):
                pkg_name = _specifier_to_package(specifier)
                if not pkg_name:
                    continue
                original = name_lookup.get(pkg_name.lower())
                if original is None:
                    continue
                report = results[original]
                report.import_count += 1
                report.files.append(FileRef(
                    path=rel_path, line=line_no, symbol=specifier,
                ))
                seen_files[original].add(rel_path)

    for name in package_names:
        results[name].file_count = len(seen_files[name])

    return results


def _walk_javascript_files(root: Path, exclude_dirs: set[str]):
    """Yield JS/TS files under root, skipping excluded directories.

    Uses a single Path.rglob pass with suffix filtering instead of
    one rglob per extension.
    """
    if not root.is_dir():
        return
    for item in root.rglob("*"):
        if item.suffix not in _JS_EXTENSIONS:
            continue
        if any(p in exclude_dirs for p in item.relative_to(root).parts[:-1]):
            continue
        if not item.is_file():
            continue
        yield item


def _extract_js_specifiers(line: str) -> list[str]:
    """Extract all import specifiers from a single line of JS/TS code."""
    specifiers: list[str] = []
    for m in _RE_REQUIRE.finditer(line):
        specifiers.append(m.group(1))
    for m in _RE_IMPORT_FROM.finditer(line):
        specifiers.append(m.group(1))
    for m in _RE_DYNAMIC_IMPORT.finditer(line):
        specifiers.append(m.group(1))
    return specifiers


def _specifier_to_package(specifier: str) -> str | None:
    """Extract the package name from an import specifier.

    "./foo" and "../bar" are relative imports — skip.
    "@scope/pkg/sub" → "@scope/pkg"
    "pkg/sub" → "pkg"
    """
    if specifier.startswith(".") or specifier.startswith("/"):
        return None
    if specifier.startswith("@"):
        # Scoped package: @scope/name
        parts = specifier.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return None
    return specifier.split("/")[0]


# ---------------------------------------------------------------------------
# Rust import scanning
# ---------------------------------------------------------------------------

_RUST_EXCLUDE = {
    "target", ".git", "vendor", "build",
}

# Matches: use serde::Serialize; or use serde;
_RE_USE = re.compile(r"^\s*use\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:::|;)")

# Matches: extern crate serde;  or  extern crate serde as _;
_RE_EXTERN_CRATE = re.compile(r"^\s*extern\s+crate\s+([a-zA-Z_][a-zA-Z0-9_]*)")


def scan_rust_imports(
    source_root: Path,
    package_names: set[str],
    exclude_dirs: set[str] | None = None,
) -> dict[str, UsageReport]:
    """Walk .rs files, find use/extern crate statements matching package names."""
    if exclude_dirs is None:
        exclude_dirs = _RUST_EXCLUDE

    # Cargo crate names use hyphens (serde-json) but Rust imports use
    # underscores (serde_json).  Build underscore→original name lookup.
    name_lookup: dict[str, str] = {}
    for name in package_names:
        import_name = name.replace("-", "_")
        name_lookup[import_name.lower()] = name

    results: dict[str, UsageReport] = {name: UsageReport() for name in package_names}
    seen_files: dict[str, set[str]] = {name: set() for name in package_names}

    for rs_file in _walk_rust_files(source_root, exclude_dirs):
        try:
            source = rs_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = str(rs_file.relative_to(source_root))

        for line_no, line in enumerate(source.splitlines(), 1):
            matched = _match_rust_import(line, name_lookup)
            if matched is None:
                continue
            pkg_name, symbol = matched
            report = results[pkg_name]
            report.import_count += 1
            report.files.append(FileRef(
                path=rel_path, line=line_no, symbol=symbol,
            ))
            seen_files[pkg_name].add(rel_path)

    for name in package_names:
        results[name].file_count = len(seen_files[name])

    return results


def _walk_rust_files(root: Path, exclude_dirs: set[str]):
    """Yield .rs files under root, skipping excluded directories."""
    if not root.is_dir():
        return
    for item in root.rglob("*.rs"):
        if any(p in exclude_dirs for p in item.relative_to(root).parts[:-1]):
            continue
        yield item


def _match_rust_import(
    line: str,
    name_lookup: dict[str, str],
) -> tuple[str, str] | None:
    """Check if a line contains a use or extern crate matching one of our packages."""
    m = _RE_USE.match(line)
    if m:
        crate = m.group(1).lower()
        original = name_lookup.get(crate)
        if original is not None:
            return original, line.strip()

    m = _RE_EXTERN_CRATE.match(line)
    if m:
        crate = m.group(1).lower()
        original = name_lookup.get(crate)
        if original is not None:
            return original, line.strip()

    return None
