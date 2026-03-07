"""Tests for lockfile parsing."""

from pathlib import Path

from dep_audit.ecosystems import detect_ecosystem
from dep_audit.lockfiles import normalize_package_name, parse_from_content
from dep_audit.lockfiles_pkg.python import (
    _parse_pyproject_deps,
    _parse_pyproject_deps_content,
    _parse_requirements_txt,
    _parse_requirements_txt_content,
)


def test_normalize_hyphens():
    assert normalize_package_name("my-package") == "my-package"


def test_normalize_underscores():
    assert normalize_package_name("my_package") == "my-package"


def test_normalize_dots():
    assert normalize_package_name("my.package") == "my-package"


def test_normalize_mixed():
    assert normalize_package_name("My_Package.Name") == "my-package-name"


def test_detect_ecosystem_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    ecosystems = detect_ecosystem(tmp_path)
    assert "python" in ecosystems


def test_detect_ecosystem_npm(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}\n")
    ecosystems = detect_ecosystem(tmp_path)
    assert "npm" in ecosystems


def test_detect_ecosystem_none(tmp_path: Path):
    ecosystems = detect_ecosystem(tmp_path)
    assert ecosystems == []


def test_detect_ecosystem_multiple(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "package.json").write_text("{}\n")
    ecosystems = detect_ecosystem(tmp_path)
    assert "python" in ecosystems
    assert "npm" in ecosystems


def test_parse_requirements_txt(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.31.0\nflask>=2.0\n# comment\npytz\n")
    result = _parse_requirements_txt(req)
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "flask" in names
    assert "pytz" in names
    # requests should have version extracted
    req_dep = next(d for d in result.deps if d.name == "requests")
    assert req_dep.version == "2.31.0"


def test_parse_requirements_txt_skips_flags(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("-r base.txt\n-e ./local\nrequests==2.31.0\n")
    result = _parse_requirements_txt(req)
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert len(result.deps) == 1


def test_parse_pyproject_deps(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["requests>=2.28", "flask~=2.0"]\n'
    )
    result = _parse_pyproject_deps(pyproject, include_dev=False)
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "flask" in names
    assert all(d.is_direct for d in result.deps)


def test_parse_pyproject_deps_with_dev(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["requests>=2.28"]\n\n'
        '[dependency-groups]\ndev = ["pytest>=8.0"]\n'
    )
    result = _parse_pyproject_deps(pyproject, include_dev=True)
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "pytest" in names


# --- Content-based parsers ---


def test_parse_requirements_txt_content():
    content = "requests==2.31.0\nflask>=2.0\n# comment\npytz\n"
    result = _parse_requirements_txt_content(content, source_label="test")
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "flask" in names
    assert "pytz" in names


def test_parse_pyproject_deps_content():
    content = '[project]\ndependencies = ["requests>=2.28", "flask~=2.0"]\n'
    result = _parse_pyproject_deps_content(content, include_dev=False)
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "flask" in names


def test_parse_from_content_empty_bundle():
    result = parse_from_content("python", {})
    assert result.deps == []


def test_parse_from_content_requirements():
    bundle = {"requirements.txt": "requests==2.31.0\npytz==2023.3\n"}
    result = parse_from_content("python", bundle)
    assert len(result.deps) == 2
    names = {d.name for d in result.deps}
    assert "requests" in names
    assert "pytz" in names


def test_parse_from_content_pyproject_priority():
    """pyproject.toml should be preferred over requirements.txt."""
    bundle = {
        "pyproject.toml": '[project]\ndependencies = ["django>=4.0"]\n',
        "requirements.txt": "flask==2.0\n",
    }
    result = parse_from_content("python", bundle)
    names = {d.name for d in result.deps}
    assert "django" in names
    # requirements.txt should be ignored since pyproject.toml was found
    assert "flask" not in names


def test_parse_from_content_unknown_ecosystem():
    result = parse_from_content("ruby", {"Gemfile": "gem 'rails'\n"})
    assert result.deps == []


# --- Inline ignores ---


def test_inline_ignore_in_requirements_txt_content():
    content = "requests==2.31.0\nsix==1.16.0  # dep-audit: ignore\npytz\n"
    result = _parse_requirements_txt_content(content, source_label="test")
    names = {d.name for d in result.deps}
    # Package is still in deps list
    assert "six" in names
    # But recorded as inline_ignore
    assert "six" in result.inline_ignores
    # Others are not ignored
    assert "requests" not in result.inline_ignores
    assert "pytz" not in result.inline_ignores


def test_inline_ignore_filesystem(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.31.0\nsix==1.16.0  # dep-audit: ignore\n")
    result = _parse_requirements_txt(req)
    assert "six" in result.inline_ignores
    assert "requests" not in result.inline_ignores


def test_no_inline_ignores_when_absent(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.31.0\npytz==2023.3\n")
    result = _parse_requirements_txt(req)
    assert result.inline_ignores == set()
