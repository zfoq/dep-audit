"""Tests for the Python import scanner."""

from pathlib import Path

from dep_audit.usage import scan_python_imports


def test_scan_finds_import(tmp_path: Path):
    """Basic 'import X' should be detected."""
    (tmp_path / "app.py").write_text("import six\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 1
    assert result["six"].file_count == 1
    assert result["six"].files[0].path == "app.py"


def test_scan_finds_from_import(tmp_path: Path):
    """'from X import Y' should be detected."""
    (tmp_path / "app.py").write_text("from pytz import timezone\n")
    result = scan_python_imports(tmp_path, {"pytz"})
    assert result["pytz"].import_count == 1


def test_scan_finds_submodule_import(tmp_path: Path):
    """'from X.sub import Y' should match the top-level package."""
    (tmp_path / "app.py").write_text("from six.moves.urllib.parse import urlparse\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 1


def test_scan_hyphenated_package(tmp_path: Path):
    """PyPI hyphens should match Python underscores in imports."""
    (tmp_path / "app.py").write_text("import importlib_metadata\n")
    result = scan_python_imports(tmp_path, {"importlib-metadata"})
    assert result["importlib-metadata"].import_count == 1


def test_scan_no_match(tmp_path: Path):
    """Imports of other packages should not match."""
    (tmp_path / "app.py").write_text("import os\nimport json\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 0


def test_scan_multiple_files(tmp_path: Path):
    """Imports across multiple files should be counted correctly."""
    (tmp_path / "a.py").write_text("import six\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("from six import text_type\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 2
    assert result["six"].file_count == 2


def test_scan_skips_excluded_dirs(tmp_path: Path):
    """Imports inside excluded directories should be ignored."""
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "lib.py").write_text("import six\n")
    (tmp_path / "app.py").write_text("import os\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 0


def test_scan_handles_syntax_error(tmp_path: Path):
    """Files with syntax errors should be skipped, not crash."""
    (tmp_path / "broken.py").write_text("def (:\n")
    (tmp_path / "good.py").write_text("import six\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 1


def test_scan_empty_project(tmp_path: Path):
    """Scanning a project with no .py files should return empty reports."""
    (tmp_path / "README.md").write_text("hello\n")
    result = scan_python_imports(tmp_path, {"six"})
    assert result["six"].import_count == 0
