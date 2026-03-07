"""Tests for Go import scanning."""

from pathlib import Path

from dep_audit.usage import scan_go_imports


def _write_go(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_scan_single_import(tmp_path: Path):
    """Single-line import should be matched."""
    _write_go(tmp_path / "main.go", 'import "github.com/sirupsen/logrus"\n')
    result = scan_go_imports(tmp_path, {"github.com/sirupsen/logrus"})
    assert result["github.com/sirupsen/logrus"].import_count == 1


def test_scan_import_block(tmp_path: Path):
    """Import block should match all listed paths."""
    src = (
        'import (\n'
        '    "github.com/pkg/errors"\n'
        '    "github.com/sirupsen/logrus"\n'
        ')\n'
    )
    _write_go(tmp_path / "main.go", src)
    result = scan_go_imports(
        tmp_path,
        {"github.com/pkg/errors", "github.com/sirupsen/logrus"},
    )
    assert result["github.com/pkg/errors"].import_count == 1
    assert result["github.com/sirupsen/logrus"].import_count == 1


def test_scan_subpackage_prefix_match(tmp_path: Path):
    """Import of a sub-package should match the parent module path."""
    # e.g. import "github.com/sirupsen/logrus/hooks/syslog" → logrus module
    _write_go(
        tmp_path / "main.go",
        'import "github.com/sirupsen/logrus/hooks/syslog"\n',
    )
    result = scan_go_imports(tmp_path, {"github.com/sirupsen/logrus"})
    assert result["github.com/sirupsen/logrus"].import_count == 1


def test_scan_aliased_import(tmp_path: Path):
    """Aliased import (alias "path") should still be matched."""
    _write_go(tmp_path / "main.go", 'import log "github.com/sirupsen/logrus"\n')
    result = scan_go_imports(tmp_path, {"github.com/sirupsen/logrus"})
    assert result["github.com/sirupsen/logrus"].import_count == 1


def test_scan_no_match(tmp_path: Path):
    """Standard library import should not match a module in the set."""
    _write_go(tmp_path / "main.go", 'import "fmt"\n')
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    assert result["github.com/pkg/errors"].import_count == 0


def test_scan_excludes_vendor(tmp_path: Path):
    """Files under vendor/ should not be scanned."""
    _write_go(tmp_path / "main.go", 'import "github.com/pkg/errors"\n')
    _write_go(
        tmp_path / "vendor" / "github.com" / "pkg" / "errors" / "errors.go",
        'import "github.com/pkg/errors"\n',
    )
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    assert result["github.com/pkg/errors"].import_count == 1  # only main.go


def test_scan_excludes_testdata(tmp_path: Path):
    """Files under testdata/ should not be scanned."""
    _write_go(tmp_path / "main.go", 'import "github.com/pkg/errors"\n')
    _write_go(
        tmp_path / "testdata" / "example.go",
        'import "github.com/pkg/errors"\n',
    )
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    assert result["github.com/pkg/errors"].import_count == 1


def test_scan_multiple_files(tmp_path: Path):
    """Imports across multiple files should be counted together."""
    _write_go(tmp_path / "a.go", 'import "github.com/pkg/errors"\n')
    _write_go(tmp_path / "b.go", 'import "github.com/pkg/errors"\n')
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    assert result["github.com/pkg/errors"].import_count == 2
    assert result["github.com/pkg/errors"].file_count == 2


def test_scan_file_ref_symbol(tmp_path: Path):
    """FileRef.symbol should be the full import path."""
    _write_go(tmp_path / "main.go", 'import "github.com/pkg/errors"\n')
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    ref = result["github.com/pkg/errors"].files[0]
    assert ref.symbol == "github.com/pkg/errors"


def test_scan_empty_dir(tmp_path: Path):
    """No .go files → zero counts for all modules."""
    result = scan_go_imports(tmp_path, {"github.com/pkg/errors"})
    assert result["github.com/pkg/errors"].import_count == 0
    assert result["github.com/pkg/errors"].file_count == 0
