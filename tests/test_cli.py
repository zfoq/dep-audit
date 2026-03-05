"""Tests for the CLI entry point."""

from dep_audit.cli import main


def test_no_args_shows_help(capsys):
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr()
    assert "dep-audit" in captured.out


def test_scan_nonexistent_dir(capsys):
    ret = main(["scan", "/nonexistent/path/xyz"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "not a directory" in captured.err


def test_db_list(capsys):
    ret = main(["db", "list", "python"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "python:" in captured.out
    assert "stdlib_backport" in captured.out


def test_db_show_existing(capsys):
    ret = main(["db", "show", "pytz"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "pytz" in captured.out


def test_db_show_missing(capsys):
    ret = main(["db", "show", "nonexistent-xyz"])
    assert ret == 1


def test_db_validate(capsys):
    ret = main(["db", "validate", "python"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "valid" in captured.out.lower() or "entries" in captured.out.lower()


def test_check_known_package(capsys):
    """Checking a known junk package should show its classification."""
    ret = main(["check", "pytz", "--ecosystem", "python"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "stdlib_backport" in captured.out


def test_check_unknown_package(capsys):
    """Checking an unknown package should show 'ok'."""
    ret = main(["check", "requests", "--ecosystem", "python"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "ok" in captured.out


def test_cache_stats(capsys):
    ret = main(["cache", "stats"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Entries:" in captured.out


def test_scan_this_project_offline(capsys):
    """Scan dep-audit itself in offline mode — it has a pyproject.toml."""
    ret = main(["scan", ".", "--offline", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    # Should produce valid JSON output
    import json
    data = json.loads(captured.out.split("\n\n")[0])  # ignore discovery messages
    assert data["ecosystem"] == "python"


def test_db_export_offline(capsys):
    """db export --discovered should scan and report discovered entries."""
    ret = main(["db", "export", "--discovered", "--ecosystem", "python", ".", "--offline"])
    assert ret == 0
    captured = capsys.readouterr()
    # Should either print TOML entries or say no new entries
    assert "entries" in captured.err or "name =" in captured.out


def test_db_export_nonexistent_dir(capsys):
    """db export on a bad path should fail."""
    ret = main(["db", "export", "--discovered", "/nonexistent/path/xyz", "--offline"])
    assert ret == 1
