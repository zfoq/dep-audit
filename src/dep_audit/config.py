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

If target-version is not set, it is auto-detected from [project].requires-python
in pyproject.toml. CLI flags always override config values.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def load_config(project_root: Path) -> dict:
    """Load dep-audit config from .dep-audit.toml or pyproject.toml.

    Priority: .dep-audit.toml > [tool.dep-audit] in pyproject.toml.
    Returns an empty dict if neither file exists or has relevant config.
    """
    # 1. Standalone config file — works for any ecosystem
    standalone = project_root / ".dep-audit.toml"
    if standalone.exists():
        try:
            return tomllib.loads(standalone.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # 2. pyproject.toml — Python projects
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return {}

    cfg: dict = dict(data.get("tool", {}).get("dep-audit", {}))

    # Auto-detect target version from requires-python when not explicit
    if "target-version" not in cfg:
        requires_python = data.get("project", {}).get("requires-python", "")
        if requires_python:
            m = re.search(r"(\d+\.\d+)", requires_python)
            if m:
                cfg["target-version"] = m.group(1)

    return cfg
