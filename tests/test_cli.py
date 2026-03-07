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


def test_db_show_missing():
    ret = main(["db", "show", "nonexistent-xyz"])
    assert ret == 1


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


def test_db_export_nonexistent_dir():
    """db export on a bad path should fail."""
    ret = main(["db", "export", "--discovered", "/nonexistent/path/xyz", "--offline"])
    assert ret == 1


def test_scan_with_config_ignore(tmp_path, capsys):
    """Packages in [tool.dep-audit].ignore should not appear in scan output."""
    # Write a requirements.txt with a known junk package
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    # Write a pyproject.toml that ignores pytz
    (tmp_path / "pyproject.toml").write_text('[tool.dep-audit]\nignore = ["pytz"]\n')
    ret = main(["scan", str(tmp_path), "--offline", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    import json
    data = json.loads(captured.out.strip())
    classified_names = [c["name"] for c in data.get("classifications", [])]
    assert "pytz" not in classified_names


def test_scan_cli_ignore_flag(tmp_path, capsys):
    """--ignore flag should suppress the named package from scan output."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--format", "json", "--ignore", "pytz"])
    assert ret == 0
    captured = capsys.readouterr()
    import json
    data = json.loads(captured.out.strip())
    classified_names = [c["name"] for c in data.get("classifications", [])]
    assert "pytz" not in classified_names


def test_scan_inline_ignore_in_requirements(tmp_path, capsys):
    """Packages with # dep-audit: ignore should be suppressed from scan output."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3  # dep-audit: ignore\n")
    ret = main(["scan", str(tmp_path), "--offline", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    import json
    data = json.loads(captured.out.strip())
    classified_names = [c["name"] for c in data.get("classifications", [])]
    assert "pytz" not in classified_names


def test_exit_code_with_findings(tmp_path):
    """--exit-code should return 1 when flagged packages are found."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code"])
    assert ret == 1


def test_exit_code_without_findings(tmp_path):
    """--exit-code should return 0 when no flagged packages are found."""
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code"])
    assert ret == 0


def test_min_confidence_filters_low_confidence(tmp_path):
    """--min-confidence 1.0 should suppress a 0.95-confidence finding."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    # pytz has confidence ~0.95 — threshold 1.0 means only perfect-confidence findings trigger exit 1
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code", "--min-confidence", "1.0"])
    assert ret == 0


def test_min_confidence_passes_high_confidence(tmp_path):
    """--min-confidence 0.5 should still flag pytz (confidence ~0.95)."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code", "--min-confidence", "0.5"])
    assert ret == 1


def test_scan_sarif_format(tmp_path, capsys):
    """--format sarif should output valid SARIF 2.1.0 JSON."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--format", "sarif"])
    assert ret == 0
    captured = capsys.readouterr()
    import json
    data = json.loads(captured.out.strip())
    assert data["version"] == "2.1.0"
    assert len(data["runs"]) == 1
    results = data["runs"][0]["results"]
    assert any(r["ruleId"] == "DEP001" for r in results)  # stdlib_backport


def test_known_cli_suppresses_exit_code(tmp_path):
    """--known should prevent --exit-code from firing for that package."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code", "--known", "pytz"])
    assert ret == 0


def test_known_still_shows_in_report(tmp_path, capsys):
    """--known package should still appear in terminal report output."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--known", "pytz"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "pytz" in captured.out


def test_known_without_exit_code_returns_zero(tmp_path):
    """--known alone (no --exit-code) should return 0 regardless."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--known", "pytz"])
    assert ret == 0


def test_known_config_key_suppresses_exit_code(tmp_path):
    """known = [...] in config should suppress exit-code for those packages."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    (tmp_path / "pyproject.toml").write_text('[tool.dep-audit]\nknown = ["pytz"]\n')
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code"])
    assert ret == 0


def test_known_logs_suppression_note(tmp_path, capsys):
    """When known findings are suppressed, a note should appear in stderr."""
    (tmp_path / "requirements.txt").write_text("pytz==2023.3\n")
    ret = main(["scan", str(tmp_path), "--offline", "--exit-code", "--known", "pytz"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "known finding" in captured.err
