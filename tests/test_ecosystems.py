"""Tests for the ecosystem registry."""

import sys

from dep_audit import ecosystems


def test_python_registered():
    eco = ecosystems.get("python")
    assert eco.name == "python"
    assert eco.system_name == "pypi"
    assert eco.display_name == "Python"


def test_npm_registered():
    eco = ecosystems.get("npm")
    assert eco.name == "npm"
    assert eco.system_name == "npm"
    assert eco.display_name == "npm"


def test_cargo_registered():
    eco = ecosystems.get("cargo")
    assert eco.name == "cargo"
    assert eco.system_name == "cargo"
    assert eco.display_name == "Rust"


def test_all_ecosystems_returns_all():
    names = {e.name for e in ecosystems.all_ecosystems()}
    assert "python" in names
    assert "npm" in names
    assert "cargo" in names


def test_display_name_known():
    assert ecosystems.display_name("python") == "Python"
    assert ecosystems.display_name("npm") == "npm"


def test_display_name_cargo():
    assert ecosystems.display_name("cargo") == "Rust"


def test_display_name_unknown_falls_back():
    assert ecosystems.display_name("maven") == "maven"


def test_resolve_target_version_python():
    version = ecosystems.resolve_target_version("python")
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert version == expected


def test_resolve_target_version_npm():
    assert ecosystems.resolve_target_version("npm") == "22.0"


def test_resolve_target_version_cargo():
    assert ecosystems.resolve_target_version("cargo") == "1.80"


def test_resolve_target_version_unknown():
    assert ecosystems.resolve_target_version("maven") == ""


def test_get_or_none():
    assert ecosystems.get_or_none("python") is not None
    assert ecosystems.get_or_none("nonexistent") is None


def test_get_raises_for_unknown():
    import pytest

    with pytest.raises(KeyError):
        ecosystems.get("nonexistent")


def test_detect_ecosystem(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    found = ecosystems.detect_ecosystem(tmp_path)
    assert "python" in found


def test_detect_ecosystem_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}\n")
    found = ecosystems.detect_ecosystem(tmp_path)
    assert "npm" in found


def test_detect_ecosystem_empty(tmp_path):
    found = ecosystems.detect_ecosystem(tmp_path)
    assert found == []


def test_python_lockfiles():
    eco = ecosystems.get("python")
    filenames = [s.file for s in eco.lockfiles]
    assert "uv.lock" in filenames
    assert "poetry.lock" in filenames


def test_python_full_lockfile_names():
    eco = ecosystems.get("python")
    assert "uv.lock" in eco.full_lockfile_names
    assert "poetry.lock" in eco.full_lockfile_names


def test_python_has_scan_imports():
    eco = ecosystems.get("python")
    assert eco.scan_imports is not None


def test_npm_has_scan_imports():
    eco = ecosystems.get("npm")
    assert eco.scan_imports is not None


def test_cargo_has_scan_imports():
    eco = ecosystems.get("cargo")
    assert eco.scan_imports is not None


def test_cargo_lockfiles():
    eco = ecosystems.get("cargo")
    filenames = [s.file for s in eco.lockfiles]
    assert "Cargo.lock" in filenames
    assert "Cargo.toml" in filenames


def test_cargo_full_lockfile_names():
    eco = ecosystems.get("cargo")
    assert "Cargo.lock" in eco.full_lockfile_names


def test_detect_ecosystem_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    found = ecosystems.detect_ecosystem(tmp_path)
    assert "cargo" in found
