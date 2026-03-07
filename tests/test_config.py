"""Tests for config.py — [tool.dep-audit] loading and auto-detection."""

from pathlib import Path

from dep_audit.config import detect_target_version, load_config


def test_no_pyproject_returns_empty(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg == {}


def test_missing_section_returns_empty(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
    cfg = load_config(tmp_path)
    assert cfg == {}


def test_reads_ignore_list(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.dep-audit]\nignore = ["six", "typing-extensions"]\n'
    )
    cfg = load_config(tmp_path)
    assert cfg["ignore"] == ["six", "typing-extensions"]


def test_reads_target_version(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dep-audit]\ntarget-version = "3.12"\n')
    cfg = load_config(tmp_path)
    assert cfg["target-version"] == "3.12"


def test_reads_offline_flag(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.dep-audit]\noffline = true\n")
    cfg = load_config(tmp_path)
    assert cfg["offline"] is True


def test_reads_exit_code_flag(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.dep-audit]\nexit-code = true\n")
    cfg = load_config(tmp_path)
    assert cfg["exit-code"] is True


def test_reads_ecosystem(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dep-audit]\necosystem = "cargo"\n')
    cfg = load_config(tmp_path)
    assert cfg["ecosystem"] == "cargo"


def test_auto_detect_target_version_from_requires_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.11"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.get("target-version") == "3.11"


def test_auto_detect_target_version_tilde_eq(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "~=3.12.0"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.get("target-version") == "3.12"


def test_explicit_target_version_not_overridden_by_requires_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.11"\n[tool.dep-audit]\ntarget-version = "3.13"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg["target-version"] == "3.13"


def test_invalid_toml_returns_empty(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("not valid toml ][[\n")
    cfg = load_config(tmp_path)
    assert cfg == {}


def test_standalone_dep_audit_toml(tmp_path: Path):
    (tmp_path / ".dep-audit.toml").write_text(
        'ignore = ["lodash"]\necosystem = "npm"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg["ignore"] == ["lodash"]
    assert cfg["ecosystem"] == "npm"


def test_standalone_takes_priority_over_pyproject(tmp_path: Path):
    (tmp_path / ".dep-audit.toml").write_text('ignore = ["from-standalone"]\n')
    (tmp_path / "pyproject.toml").write_text('[tool.dep-audit]\nignore = ["from-pyproject"]\n')
    cfg = load_config(tmp_path)
    assert cfg["ignore"] == ["from-standalone"]


def test_invalid_standalone_toml_returns_empty(tmp_path: Path):
    (tmp_path / ".dep-audit.toml").write_text("not valid toml ][[\n")
    cfg = load_config(tmp_path)
    assert cfg == {}


# --- detect_target_version ---


def test_detect_rust_version_from_cargo_toml(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "my-crate"\nversion = "0.1.0"\nrust-version = "1.70"\n'
    )
    assert detect_target_version(tmp_path, "cargo") == "1.70"


def test_detect_rust_version_three_part(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0.1.0"\nrust-version = "1.65.0"\n'
    )
    assert detect_target_version(tmp_path, "cargo") == "1.65"


def test_detect_rust_version_missing_field(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    assert detect_target_version(tmp_path, "cargo") is None


def test_detect_rust_version_no_cargo_toml(tmp_path: Path):
    assert detect_target_version(tmp_path, "cargo") is None


def test_detect_node_version_from_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"name": "x", "engines": {"node": ">=18.0.0"}}\n'
    )
    assert detect_target_version(tmp_path, "npm") == "18.0"


def test_detect_node_version_caret_range(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"engines": {"node": "^20.0.0"}}\n'
    )
    assert detect_target_version(tmp_path, "npm") == "20.0"


def test_detect_node_version_bare_major(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"engines": {"node": "18"}}\n')
    assert detect_target_version(tmp_path, "npm") == "18.0"


def test_detect_node_version_with_minor(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=18.12"}}\n')
    assert detect_target_version(tmp_path, "npm") == "18.12"


def test_detect_node_version_no_engines_field(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "x"}\n')
    assert detect_target_version(tmp_path, "npm") is None


def test_detect_node_version_no_package_json(tmp_path: Path):
    assert detect_target_version(tmp_path, "npm") is None


def test_detect_returns_none_for_python(tmp_path: Path):
    # Python version is handled by load_config, not detect_target_version
    assert detect_target_version(tmp_path, "python") is None


def test_detect_returns_none_for_unknown_ecosystem(tmp_path: Path):
    assert detect_target_version(tmp_path, "ruby") is None
