"""Go module parser: go.mod.

Content-based variants accept strings directly so we can parse go.mod files
fetched from remote repos without writing them to disk.

go.mod records both direct and indirect (transitive) requirements in a single
require block.  Direct deps have no trailing comment; indirect deps are marked
with // indirect.  go.sum is the integrity manifest but does not add
information about which deps are direct, so we parse only go.mod.
"""

from __future__ import annotations

import re
from pathlib import Path

from dep_audit.lockfiles_pkg._types import Dependency, LockfileResult


def normalize_go_module(name: str) -> str:
    """Normalize a Go module path for comparison.

    Go module paths are lowercase by convention but the ecosystem is
    technically case-sensitive (github.com/BurntSushi/toml exists).
    We lowercase for consistent matching against our DB entries.
    Unlike Python/npm we do NOT replace underscores with hyphens since
    underscores are meaningful in Go module paths.
    """
    return name.lower()


# ---------------------------------------------------------------------------
# go.mod content parser
# ---------------------------------------------------------------------------

# Matches a require block:  require ( ... )
_RE_REQUIRE_BLOCK = re.compile(r"\brequire\s*\(([^)]*)\)", re.DOTALL)

# Matches a single-line require:  require module/path v1.2.3 [// indirect]
_RE_REQUIRE_SINGLE = re.compile(
    r"^require\s+(\S+)\s+(v\S+)(.*?)$", re.MULTILINE
)

# go directive: go 1.21  (for target version detection)
_RE_GO_DIRECTIVE = re.compile(r"^go\s+(\d+\.\d+)", re.MULTILINE)

# module directive: module example.com/myapp
_RE_MODULE = re.compile(r"^module\s+(\S+)", re.MULTILINE)


def _parse_require_line(line: str) -> tuple[str, str, bool] | None:
    """Parse one line from inside a require block.

    Returns (module_path, version, is_indirect) or None.
    """
    line = line.strip()
    if not line or line.startswith("//"):
        return None

    is_indirect = "// indirect" in line
    # Strip trailing comment
    clean = line.split("//")[0].strip()
    parts = clean.split()
    if len(parts) < 2:
        return None

    name, version = parts[0], parts[1]

    # Must look like a module path (contains a dot — filters keywords)
    if "." not in name:
        return None

    return name, version, is_indirect


def _parse_go_mod_content(
    content: str,
    source_label: str = "<remote>",
) -> LockfileResult:
    """Parse go.mod content into a LockfileResult."""
    deps: list[Dependency] = []
    seen: set[str] = set()

    # Extract root module path so we can skip it
    module_match = _RE_MODULE.search(content)
    root_module = normalize_go_module(module_match.group(1)) if module_match else ""

    entries: list[tuple[str, str, bool]] = []

    # Parenthesised require blocks
    for block_match in _RE_REQUIRE_BLOCK.finditer(content):
        for line in block_match.group(1).splitlines():
            parsed = _parse_require_line(line)
            if parsed:
                entries.append(parsed)

    # Single-line requires (not inside a block)
    for m in _RE_REQUIRE_SINGLE.finditer(content):
        name_raw, version_raw, tail = m.group(1), m.group(2), m.group(3)
        if "." not in name_raw:
            continue
        is_indirect = "indirect" in tail
        entries.append((name_raw, version_raw, is_indirect))

    for name_raw, version_raw, is_indirect in entries:
        norm = normalize_go_module(name_raw)

        if norm == root_module or norm in seen:
            continue
        seen.add(norm)

        # Strip leading 'v' from version (v0.9.1 -> 0.9.1)
        version = version_raw.lstrip("v")

        deps.append(Dependency(
            name=norm,
            version=version,
            is_direct=not is_indirect,
            group="default",
        ))

    return LockfileResult(
        ecosystem="go",
        deps=deps,
        source_file=source_label,
    )


# ---------------------------------------------------------------------------
# Path-based parser (local filesystem)
# ---------------------------------------------------------------------------

def parse_go(project_root: Path, include_dev: bool = False) -> LockfileResult:
    """Parse go.mod in the given directory."""
    go_mod = project_root / "go.mod"
    if go_mod.exists():
        try:
            content = go_mod.read_text(encoding="utf-8")
        except OSError:
            return LockfileResult(ecosystem="go")
        return _parse_go_mod_content(content, str(go_mod))

    return LockfileResult(ecosystem="go")


def _parse_go_from_content(
    file_bundle: dict[str, str],
    include_dev: bool,
) -> LockfileResult:
    """Parse Go lockfiles from a content bundle (remote scans)."""
    if "go.mod" in file_bundle:
        return _parse_go_mod_content(
            file_bundle["go.mod"],
            source_label="go.mod (remote)",
        )
    return LockfileResult(ecosystem="go")
