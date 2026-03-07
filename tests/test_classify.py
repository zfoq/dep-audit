"""Tests for the classification decision tree."""

from dep_audit.classify import _parse_replacement, _version_ge, classify_package


def test_version_ge_equal():
    assert _version_ge("3.11", "3.11") is True


def test_version_ge_greater():
    assert _version_ge("3.12", "3.11") is True


def test_version_ge_less():
    assert _version_ge("3.10", "3.11") is False


def test_version_ge_major_diff():
    assert _version_ge("4.0", "3.11") is True


def test_version_ge_bad_input():
    assert _version_ge("", "3.11") is False
    assert _version_ge("abc", "3.11") is False


def test_classify_from_junk_db():
    """A package in the junk DB should be classified using its entry."""
    junk_db = {
        "pytz": {
            "type": "stdlib_backport",
            "replacement": "zoneinfo",
            "confidence": 0.95,
            "stdlib_since": "3.9",
            "flags": ["stdlib_backport: zoneinfo available since Python 3.9"],
        }
    }
    result = classify_package(
        ecosystem="python",
        name="pytz",
        version="2024.1",
        target_version="3.12",
        is_direct=True,
        junk_db=junk_db,
        offline=True,
    )
    assert result.classification == "stdlib_backport"
    assert result.replacement == "zoneinfo"
    assert result.confidence == 0.95


def test_classify_junk_db_version_too_low():
    """If target version is below stdlib_since, package should be 'ok'."""
    junk_db = {
        "tomli": {
            "type": "stdlib_backport",
            "replacement": "tomllib",
            "confidence": 0.95,
            "stdlib_since": "3.11",
            "flags": ["stdlib_backport: tomllib available since Python 3.11"],
        }
    }
    result = classify_package(
        ecosystem="python",
        name="tomli",
        version="2.0.0",
        target_version="3.10",  # below 3.11
        is_direct=True,
        junk_db=junk_db,
        offline=True,
    )
    assert result.classification == "ok"


def test_classify_unknown_package():
    """A package not in any DB should be 'ok'."""
    result = classify_package(
        ecosystem="python",
        name="requests",
        version="2.31.0",
        target_version="3.12",
        is_direct=True,
        junk_db={},
        offline=True,
    )
    assert result.classification == "ok"


def test_parse_replacement_use_instead():
    assert _parse_replacement("use requests instead") == "requests"


def test_parse_replacement_replaced_by():
    assert _parse_replacement("This package is replaced by pycryptodome") == "pycryptodome"


def test_parse_replacement_switch_to():
    assert _parse_replacement("switch to httpx for modern HTTP") == "httpx"


def test_parse_replacement_no_match():
    assert _parse_replacement("this package is no longer maintained") == ""
