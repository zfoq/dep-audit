"""deps.dev API client with file-based cache.

Uses urllib.request (stdlib) so we stay zero-dependency on 3.11+.
Every response is cached to disk to avoid hammering the API on repeated runs.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from dep_audit import cache

logger = logging.getLogger("dep_audit")

_BASE = "https://api.deps.dev/v3"


def system_name(ecosystem: str) -> str:
    """Map our ecosystem name to deps.dev's system name."""
    from dep_audit import ecosystems

    eco = ecosystems.get_or_none(ecosystem)
    return eco.system_name if eco else ecosystem


_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 10.0)


def _fetch(url: str, cache_key: str, ttl: int = cache.TTL_METADATA) -> dict | None:
    """Fetch URL with caching. Returns parsed JSON or None on failure.

    Retries with exponential backoff on HTTP 429 (rate limit).
    """
    cached = cache.get("depsdev", cache_key, ttl=ttl)
    if cached is not None:
        return cached

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            cache.put("depsdev", cache_key, data)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BACKOFF[attempt]
                logger.debug("Rate limited by deps.dev, retrying in %.0fs...", delay)
                time.sleep(delay)
                continue
            return None
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
    return None


def get_package(ecosystem: str, name: str) -> dict | None:
    """Get package info (versions list)."""
    sys_name = system_name(ecosystem)
    encoded = urllib.parse.quote(name, safe="")
    url = f"{_BASE}/systems/{sys_name}/packages/{encoded}"
    return _fetch(url, f"{sys_name}-{name}-pkg")


def get_version(ecosystem: str, name: str, version: str) -> dict | None:
    """Get version-specific metadata."""
    sys_name = system_name(ecosystem)
    encoded_name = urllib.parse.quote(name, safe="")
    encoded_ver = urllib.parse.quote(version, safe="")
    url = f"{_BASE}/systems/{sys_name}/packages/{encoded_name}/versions/{encoded_ver}"
    return _fetch(url, f"{sys_name}-{name}-{version}")


def get_dependencies(ecosystem: str, name: str, version: str) -> dict | None:
    """Get dependency tree for a specific version."""
    sys_name = system_name(ecosystem)
    encoded_name = urllib.parse.quote(name, safe="")
    encoded_ver = urllib.parse.quote(version, safe="")
    url = f"{_BASE}/systems/{sys_name}/packages/{encoded_name}/versions/{encoded_ver}:dependencies"
    return _fetch(url, f"{sys_name}-{name}-{version}-deps")


def is_deprecated(ecosystem: str, name: str, version: str) -> tuple[bool, str]:
    """Check if a package version is deprecated. Returns (is_deprecated, message)."""
    data = get_version(ecosystem, name, version)
    if data is None:
        return False, ""
    deprecated = data.get("isDeprecated", False)
    # Try to extract deprecation message from links or advisories
    msg = ""
    if deprecated:
        for link in data.get("links", []):
            label = link.get("label", "")
            if "deprecat" in label.lower():
                # Prefer label (human-readable message) over URL
                msg = label or link.get("url", "")
                break
    return deprecated, msg
