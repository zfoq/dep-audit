"""Tests for Cargo lockfile parsing."""

from pathlib import Path

from dep_audit.ecosystems import detect_ecosystem
from dep_audit.lockfiles import (
    _parse_cargo_lock_content,
    _parse_cargo_toml_content,
    parse_cargo,
    parse_from_content,
)

# A minimal Cargo.lock with a root package and two dependencies
_CARGO_LOCK = """\
version = 3

[[package]]
name = "my-project"
version = "0.1.0"
dependencies = [
    "serde",
    "once_cell",
]

[[package]]
name = "serde"
version = "1.0.193"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
    "serde_derive",
]

[[package]]
name = "serde_derive"
version = "1.0.193"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "once_cell"
version = "1.19.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""

_CARGO_TOML = """\
[package]
name = "my-project"
version = "0.1.0"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
once_cell = "1.19"

[dev-dependencies]
criterion = "0.5"
"""


def test_parse_cargo_lock_content():
    result = _parse_cargo_lock_content(_CARGO_LOCK, _CARGO_TOML, include_dev=False)
    names = {d.name for d in result.deps}
    assert "serde" in names
    assert "serde-derive" in names
    assert "once-cell" in names
    assert result.ecosystem == "cargo"


def test_parse_cargo_lock_skips_root():
    """Root package (no source) should not appear in deps."""
    result = _parse_cargo_lock_content(_CARGO_LOCK, _CARGO_TOML, include_dev=False)
    names = {d.name for d in result.deps}
    assert "my-project" not in names


def test_parse_cargo_lock_direct_detection():
    """Deps listed in Cargo.toml [dependencies] should be marked as direct."""
    result = _parse_cargo_lock_content(_CARGO_LOCK, _CARGO_TOML, include_dev=False)
    dep_map = {d.name: d for d in result.deps}
    assert dep_map["serde"].is_direct is True
    assert dep_map["once-cell"].is_direct is True
    assert dep_map["serde-derive"].is_direct is False


def test_parse_cargo_lock_tree_edges():
    """Dependency tree should be extracted from Cargo.lock dependencies."""
    result = _parse_cargo_lock_content(_CARGO_LOCK, _CARGO_TOML, include_dev=False)
    assert result.tree_edges is not None
    # serde depends on serde_derive
    assert "serde-derive" in result.tree_edges.get("serde", [])
    # root depends on serde and once_cell
    assert "serde" in result.tree_edges.get("my-project", [])
    assert "once-cell" in result.tree_edges.get("my-project", [])


def test_parse_cargo_toml_content():
    result = _parse_cargo_toml_content(_CARGO_TOML, include_dev=False)
    names = {d.name for d in result.deps}
    assert "serde" in names
    assert "once-cell" in names
    assert "criterion" not in names
    assert all(d.is_direct for d in result.deps)


def test_parse_cargo_toml_dev_deps():
    result = _parse_cargo_toml_content(_CARGO_TOML, include_dev=True)
    names = {d.name for d in result.deps}
    assert "serde" in names
    assert "criterion" in names
    dev_dep = next(d for d in result.deps if d.name == "criterion")
    assert dev_dep.group == "dev"


def test_parse_cargo_toml_version_extraction():
    """Version should be extracted from both string and table specs."""
    result = _parse_cargo_toml_content(_CARGO_TOML, include_dev=False)
    dep_map = {d.name: d for d in result.deps}
    assert dep_map["serde"].version == "1.0"
    assert dep_map["once-cell"].version == "1.19"


def test_parse_from_content_cargo():
    """Bundle parser should pick Cargo.lock over Cargo.toml."""
    bundle = {"Cargo.lock": _CARGO_LOCK, "Cargo.toml": _CARGO_TOML}
    result = parse_from_content("cargo", bundle)
    names = {d.name for d in result.deps}
    # Cargo.lock has transitive deps
    assert "serde-derive" in names
    assert result.source_file == "Cargo.lock (remote)"


def test_parse_from_content_cargo_toml_only():
    """Without Cargo.lock, should fall back to Cargo.toml."""
    bundle = {"Cargo.toml": _CARGO_TOML}
    result = parse_from_content("cargo", bundle)
    names = {d.name for d in result.deps}
    assert "serde" in names
    # Cargo.toml fallback has no transitive deps
    assert "serde-derive" not in names


def test_parse_cargo_filesystem(tmp_path: Path):
    (tmp_path / "Cargo.lock").write_text(_CARGO_LOCK)
    (tmp_path / "Cargo.toml").write_text(_CARGO_TOML)
    result = parse_cargo(tmp_path)
    names = {d.name for d in result.deps}
    assert "serde" in names
    assert "once-cell" in names


def test_parse_cargo_filesystem_toml_only(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(_CARGO_TOML)
    result = parse_cargo(tmp_path)
    names = {d.name for d in result.deps}
    assert "serde" in names


def test_parse_cargo_filesystem_empty(tmp_path: Path):
    result = parse_cargo(tmp_path)
    assert result.deps == []


def test_detect_ecosystem_cargo(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    found = detect_ecosystem(tmp_path)
    assert "cargo" in found


def test_parse_cargo_lock_no_cargo_toml():
    """Without Cargo.toml, all packages should be marked as not direct."""
    result = _parse_cargo_lock_content(_CARGO_LOCK, None, include_dev=False)
    assert all(not d.is_direct for d in result.deps)
