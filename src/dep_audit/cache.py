"""File-based JSON cache for API responses.

One JSON file per cached entry, keyed by SHA-256 of the cache key.
TTL is checked via file mtime — no cleanup daemon needed.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

_DEFAULT_DIR = Path.home() / ".cache" / "dep-audit"

TTL_METADATA = 24 * 3600  # 24 hours
TTL_ADVISORY = 6 * 3600   # 6 hours


def _cache_dir() -> Path:
    d = _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_path(namespace: str, key: str) -> Path:
    safe = hashlib.sha256(key.encode()).hexdigest()[:32]
    d = _cache_dir() / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def get(namespace: str, key: str, ttl: int = TTL_METADATA) -> dict | None:
    """Return cached value or None if missing/expired."""
    p = _key_path(namespace, key)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > ttl:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def put(namespace: str, key: str, value: dict) -> None:
    """Store a value in the cache."""
    p = _key_path(namespace, key)
    p.write_text(json.dumps(value, default=str), encoding="utf-8")


def clear() -> None:
    """Delete all cached files and remove empty directories."""
    import contextlib

    d = _cache_dir()
    if not d.exists():
        return
    # Single bottom-up traversal: delete files and rmdir empty dirs
    for child in sorted(d.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            with contextlib.suppress(OSError):
                child.rmdir()
