"""deps.dev API client with file-based cache.

Uses urllib.request (stdlib) so we stay zero-dependency on 3.11+.
Every response is cached to disk to avoid hammering the API on repeated runs.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from dep_audit import cache

_BASE = "https://api.deps.dev/v3"

# deps.dev calls ecosystems "systems" — map our names to theirs
_SYSTEM_MAP = {
    "python": "pypi",
    "npm": "npm",
    "cargo": "cargo",
    "maven": "maven",
}


def _system(ecosystem: str) -> str:
    return _SYSTEM_MAP.get(ecosystem, ecosystem)


def _fetch(url: str, cache_key: str, ttl: int = cache._TTL_METADATA) -> dict | None:
    """Fetch URL with caching. Returns parsed JSON or None on failure."""
    cached = cache.get("depsdev", cache_key, ttl=ttl)
    if cached is not None:
        return cached

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        cache.put("depsdev", cache_key, data)
        return data
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        # Network down, timeout, bad JSON — all treated the same: unavailable
        return None


def get_package(ecosystem: str, name: str) -> dict | None:
    """Get package info (versions list)."""
    sys = _system(ecosystem)
    encoded = urllib.parse.quote(name, safe="")
    url = f"{_BASE}/systems/{sys}/packages/{encoded}"
    return _fetch(url, f"{sys}-{name}-pkg")


def get_version(ecosystem: str, name: str, version: str) -> dict | None:
    """Get version-specific metadata."""
    sys = _system(ecosystem)
    encoded_name = urllib.parse.quote(name, safe="")
    encoded_ver = urllib.parse.quote(version, safe="")
    url = f"{_BASE}/systems/{sys}/packages/{encoded_name}/versions/{encoded_ver}"
    return _fetch(url, f"{sys}-{name}-{version}")


def get_dependencies(ecosystem: str, name: str, version: str) -> dict | None:
    """Get dependency tree for a specific version."""
    sys = _system(ecosystem)
    encoded_name = urllib.parse.quote(name, safe="")
    encoded_ver = urllib.parse.quote(version, safe="")
    url = f"{_BASE}/systems/{sys}/packages/{encoded_name}/versions/{encoded_ver}:dependencies"
    return _fetch(url, f"{sys}-{name}-{version}-deps")


def get_project(project_key: str) -> dict | None:
    """Get project info (Scorecard, etc). project_key like 'github.com/user/repo'."""
    encoded = urllib.parse.quote(project_key, safe="")
    url = f"{_BASE}/projects/{encoded}"
    return _fetch(url, f"project-{project_key}")


def get_advisory(advisory_key: str) -> dict | None:
    """Get advisory details."""
    encoded = urllib.parse.quote(advisory_key, safe="")
    url = f"{_BASE}/advisories/{encoded}"
    return _fetch(url, f"advisory-{advisory_key}", ttl=cache._TTL_ADVISORY)


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
            label = link.get("label", "").lower()
            if "deprecat" in label:
                msg = link.get("url", "")
                break
    return deprecated, msg


def get_scorecard_maintained(project_key: str) -> int | None:
    """Get Scorecard 'Maintained' score (0-10) for a project. Returns None if unavailable."""
    data = get_project(project_key)
    if data is None:
        return None
    scorecard = data.get("scorecard", {})
    for check in scorecard.get("checks", []):
        if check.get("name") == "Maintained":
            return check.get("score", 0)
    return None


def get_dependents_count(ecosystem: str, name: str) -> dict[str, int]:
    """Get dependent counts. Returns {'direct': N, 'indirect': N}."""
    sys = _system(ecosystem)
    encoded = urllib.parse.quote(name, safe="")
    url = f"{_BASE}/systems/{sys}/packages/{encoded}/dependents"
    # The dependents endpoint might not exist in v3; we fetch what we can
    data = _fetch(url, f"{sys}-{name}-depnts")
    if data is None:
        return {"direct": 0, "indirect": 0}
    return {
        "direct": data.get("directCount", 0),
        "indirect": data.get("indirectCount", 0),
    }


def enrich_package(ecosystem: str, name: str, version: str) -> dict[str, Any]:
    """Fetch all available metadata for a package version. Returns a combined dict."""
    result: dict[str, Any] = {
        "name": name,
        "version": version,
        "ecosystem": ecosystem,
    }

    ver_data = get_version(ecosystem, name, version)
    if ver_data:
        result["is_deprecated"] = ver_data.get("isDeprecated", False)
        result["licenses"] = list(ver_data.get("licenses", []))
        result["advisory_keys"] = [a.get("id", "") for a in ver_data.get("advisoryKeys", [])]
        result["published_at"] = ver_data.get("publishedAt", "")
        result["links"] = ver_data.get("links", [])

    deps_count = get_dependents_count(ecosystem, name)
    result["dependents_direct"] = deps_count["direct"]
    result["dependents_indirect"] = deps_count["indirect"]

    return result
