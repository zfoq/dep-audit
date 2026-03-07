"""Load dep-audit configuration from the project root.

Config is read from the first file found, in priority order:
  1. .dep-audit.toml          (standalone, works for any ecosystem)
  2. pyproject.toml           ([tool.dep-audit] section, Python projects)

Supported keys:
  ignore = ["typing-extensions", "six"]   # suppress specific packages
  target-version = "3.11"                 # override language version
  ecosystem = "python"                    # force ecosystem
  offline = true                          # skip deps.dev API
  exit-code = true                        # non-zero exit on findings
  min-confidence = 0.8                    # with exit-code: minimum confidence to trigger failure

If target-version is not set, it is auto-detected from the project manifest:
  Python  — [project].requires-python in pyproject.toml
  Rust    — package.rust-version in Cargo.toml
  npm     — engines.node in package.json
CLI flags always override config and auto-detected values.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import Path

logger = logging.getLogger("dep_audit")

_KNOWN_KEYS = frozenset({"ignore", "target-version", "ecosystem", "offline", "exit-code", "min-confidence"})


def load_config(project_root: Path) -> dict:
    """Load dep-audit config from .dep-audit.toml or pyproject.toml.

    Priority: .dep-audit.toml > [tool.dep-audit] in pyproject.toml.
    Returns an empty dict if neither file exists or has relevant config.
    """
    # 1. Standalone config file — works for any ecosystem
    standalone = project_root / ".dep-audit.toml"
    if standalone.exists():
        try:
            cfg = tomllib.loads(standalone.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Could not parse .dep-audit.toml: %s", e)
            return {}
        for key in cfg:
            if key not in _KNOWN_KEYS:
                logger.warning("Unknown dep-audit config key %r (ignored)", key)
        return cfg

    # 2. pyproject.toml — Python projects
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not parse pyproject.toml: %s", e)
        return {}

    cfg: dict = dict(data.get("tool", {}).get("dep-audit", {}))
    for key in cfg:
        if key not in _KNOWN_KEYS:
            logger.warning("Unknown dep-audit config key %r (ignored)", key)

    # Auto-detect Python target version from requires-python when not explicit
    if "target-version" not in cfg:
        requires_python = data.get("project", {}).get("requires-python", "")
        if requires_python:
            m = re.search(r"(\d+\.\d+)", requires_python)
            if m:
                cfg["target-version"] = m.group(1)

    return cfg


def detect_target_version_from_bundle(bundle: dict[str, str], ecosystem: str) -> str | None:
    """Auto-detect target version from in-memory file bundle (remote scans).

    Same logic as detect_target_version but works on fetched file contents
    instead of reading from disk. Returns None if version can't be determined.
    """
    if ecosystem == "cargo":
        content = bundle.get("Cargo.toml", "")
        if not content:
            return None
        try:
            data = tomllib.loads(content)
        except Exception:
            return None
        version = data.get("package", {}).get("rust-version", "")
        if not version:
            return None
        m = re.search(r"(\d+\.\d+)", str(version))
        return m.group(1) if m else None

    if ecosystem == "npm":
        content = bundle.get("package.json", "")
        if not content:
            return None
        try:
            data = json.loads(content)
        except Exception:
            return None
        node_range = data.get("engines", {}).get("node", "")
        if not node_range:
            return None
        m = re.search(r"(\d+\.\d+|\d+)", str(node_range))
        if not m:
            return None
        version = m.group(1)
        return version if "." in version else f"{version}.0"

    return None


def detect_target_version(project_root: Path, ecosystem: str) -> str | None:
    """Auto-detect the target language version from the project manifest.

    Returns the version string if found, or None to fall back to the
    ecosystem's hardcoded default. The caller's explicit --target-version
    or config file value always takes precedence over this.

    Rust  — package.rust-version in Cargo.toml  (e.g. "1.70")
    npm   — engines.node in package.json         (e.g. ">=18.0.0" → "18.0")
    Python is handled by load_config() via requires-python.
    """
    if ecosystem == "cargo":
        return _detect_rust_version(project_root)
    if ecosystem == "npm":
        return _detect_node_version(project_root)
    return None


def _detect_rust_version(project_root: Path) -> str | None:
    """Read package.rust-version from Cargo.toml."""
    cargo_toml = project_root / "Cargo.toml"
    if not cargo_toml.exists():
        return None
    try:
        data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = data.get("package", {}).get("rust-version", "")
    if not version:
        return None
    # rust-version is always a plain semver like "1.70" or "1.70.0"
    m = re.search(r"(\d+\.\d+)", str(version))
    return m.group(1) if m else None


def _detect_node_version(project_root: Path) -> str | None:
    """Read engines.node from package.json."""
    pkg_json = project_root / "package.json"
    if not pkg_json.exists():
        return None
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    node_range = data.get("engines", {}).get("node", "")
    if not node_range:
        return None
    # Extract the first version number from a range like ">=18.0.0" or "^20" or "18"
    m = re.search(r"(\d+\.\d+|\d+)", str(node_range))
    if not m:
        return None
    version = m.group(1)
    # Normalise bare major like "18" to "18.0"
    return version if "." in version else f"{version}.0"
