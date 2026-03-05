"""Tests for Rust import scanning."""

from pathlib import Path

from dep_audit.usage import scan_rust_imports


def test_scan_use_statement(tmp_path: Path):
    """use serde::Serialize; should match the serde crate."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("use serde::Serialize;\nuse serde::Deserialize;\n")
    result = scan_rust_imports(tmp_path, {"serde"})
    assert result["serde"].import_count == 2
    assert result["serde"].file_count == 1


def test_scan_extern_crate(tmp_path: Path):
    """extern crate lazy_static; should match the lazy-static crate."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text("extern crate lazy_static;\n")
    result = scan_rust_imports(tmp_path, {"lazy-static"})
    assert result["lazy-static"].import_count == 1


def test_scan_hyphen_underscore_mapping(tmp_path: Path):
    """Crate serde-json should be found via use serde_json::..."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("use serde_json::Value;\n")
    result = scan_rust_imports(tmp_path, {"serde-json"})
    assert result["serde-json"].import_count == 1


def test_scan_excludes_target_dir(tmp_path: Path):
    """Files under target/ should not be scanned."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("use serde::Serialize;\n")
    target = tmp_path / "target" / "debug"
    target.mkdir(parents=True)
    (target / "generated.rs").write_text("use serde::Serialize;\n")
    result = scan_rust_imports(tmp_path, {"serde"})
    assert result["serde"].import_count == 1  # only from src/


def test_scan_no_match(tmp_path: Path):
    """Unrelated imports should not be counted."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("use std::collections::HashMap;\n")
    result = scan_rust_imports(tmp_path, {"serde"})
    assert result["serde"].import_count == 0


def test_scan_multiple_crates(tmp_path: Path):
    """Multiple crates should be tracked independently."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text(
        "use serde::Serialize;\n"
        "use once_cell::sync::Lazy;\n"
        "use serde::Deserialize;\n"
    )
    result = scan_rust_imports(tmp_path, {"serde", "once-cell"})
    assert result["serde"].import_count == 2
    assert result["once-cell"].import_count == 1


def test_scan_use_bare(tmp_path: Path):
    """use crate_name; (without ::) should also match."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("use serde;\n")
    result = scan_rust_imports(tmp_path, {"serde"})
    assert result["serde"].import_count == 1


def test_scan_file_ref_details(tmp_path: Path):
    """FileRef should contain path, line, and symbol."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\nuse serde::Serialize;\n")
    result = scan_rust_imports(tmp_path, {"serde"})
    assert len(result["serde"].files) == 1
    ref = result["serde"].files[0]
    assert ref.line == 2
    assert "serde" in ref.symbol
