"""Shared utilities for lockfile parsers."""

from __future__ import annotations

import re


def normalize_package_name(name: str) -> str:
    """Normalize a Python package name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower().strip()
