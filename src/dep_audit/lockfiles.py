"""Lockfile parsers — re-exports from the lockfiles_pkg package.

This module exists for backwards compatibility. The actual implementation
lives in dep_audit.lockfiles_pkg, split by ecosystem (python.py, npm.py).
"""

# Re-export everything from the package so existing imports work unchanged
from dep_audit.lockfiles_pkg import *  # noqa: F401, F403
