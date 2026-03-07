"""Shared utilities for lockfile parsers."""

from __future__ import annotations

import re


def normalize_package_name(name: str) -> str:
    """Normalize a package name: collapse hyphens, underscores, and dots to a single hyphen.

    Covers PEP 503 for Python and is coincidentally correct for Cargo crate names,
    which use the same separator-collapsing convention.
    """
    return re.sub(r"[-_.]+", "-", name).lower().strip()
