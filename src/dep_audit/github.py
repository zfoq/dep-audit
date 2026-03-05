"""Fetch lockfiles from public GitHub repos via raw.githubusercontent.com.

Uses urllib.request (stdlib) — same approach as depsdev.py.
Responses are cached so repeated scans of the same repo don't re-download.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from dep_audit import cache

_RAW_BASE = "https://raw.githubusercontent.com"
_TTL_REMOTE = 3600  # 1 hour — lockfiles don't change that often


@dataclass
class RepoRef:
    owner: str
    repo: str
    ref: str = "HEAD"


# Lockfile names to probe, grouped by ecosystem.
# Order matters — first found wins (same priority as lockfiles.py).
# "companions" are extra files fetched alongside the lockfile (e.g. pyproject.toml
# is needed by the uv.lock parser to figure out which deps are direct).
_LOCKFILE_MAP: dict[str, list[dict]] = {
    "python": [
        {"file": "uv.lock", "companions": ["pyproject.toml"]},
        {"file": "poetry.lock", "companions": ["pyproject.toml"]},
        {"file": "pyproject.toml", "companions": []},
        {"file": "requirements.txt", "companions": []},
    ],
    "npm": [
        {"file": "package-lock.json", "companions": ["package.json"]},
        {"file": "yarn.lock", "companions": ["package.json"]},
        {"file": "pnpm-lock.yaml", "companions": ["package.json"]},
        {"file": "package.json", "companions": []},
    ],
    "cargo": [
        {"file": "Cargo.lock", "companions": ["Cargo.toml"]},
        {"file": "Cargo.toml", "companions": []},
    ],
}

# Marker files for ecosystem detection — if any of these exist, that
# ecosystem is present. We only probe the ones that are cheap (one HTTP each).
_ECOSYSTEM_MARKERS: dict[str, list[str]] = {
    "python": ["uv.lock", "poetry.lock", "pyproject.toml", "requirements.txt", "setup.py"],
    "npm": ["package.json"],
    "cargo": ["Cargo.toml"],
}


def parse_github_url(url_or_shorthand: str) -> RepoRef | None:
    """Parse a GitHub URL or owner/repo shorthand into a RepoRef.

    Accepts:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - github.com/owner/repo
      - owner/repo  (if it looks like one — no dots, slashes, or leading .//)
    """
    s = url_or_shorthand.strip().rstrip("/")

    # Full URL: https://github.com/owner/repo
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", s)
    if m:
        return RepoRef(owner=m.group(1), repo=m.group(2))

    # Without scheme: github.com/owner/repo
    m = re.match(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$", s)
    if m:
        return RepoRef(owner=m.group(1), repo=m.group(2))

    # Shorthand: owner/repo — must look like two simple names separated by /
    m = re.match(r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)$", s)
    if m:
        # Make sure it's not a local relative path
        owner, repo = m.group(1), m.group(2)
        if owner.startswith(".") or owner.startswith("/"):
            return None
        return RepoRef(owner=owner, repo=repo)

    return None


def is_github_target(path_str: str) -> bool:
    """Quick check: does this look like a GitHub URL/shorthand rather than a local path?"""
    return parse_github_url(path_str) is not None


def fetch_file(repo: RepoRef, path: str) -> str | None:
    """Fetch a single file from a GitHub repo. Returns content or None if not found."""
    cache_key = f"{repo.owner}/{repo.repo}/{repo.ref}/{path}"

    # Check cache first — store as {"content": "..."} wrapper since cache expects dicts
    cached = cache.get("github", cache_key, ttl=_TTL_REMOTE)
    if cached is not None:
        return cached.get("content")

    url = f"{_RAW_BASE}/{repo.owner}/{repo.repo}/{repo.ref}/{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
        cache.put("github", cache_key, {"content": content})
        return content
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        # Other HTTP errors (rate limit, server error) — treat as unavailable
        return None
    except (urllib.error.URLError, OSError):
        return None


def detect_remote_ecosystem(repo: RepoRef) -> list[str]:
    """Detect ecosystems by probing for marker files in the repo root."""
    found: list[str] = []
    for eco, markers in _ECOSYSTEM_MARKERS.items():
        for marker in markers:
            content = fetch_file(repo, marker)
            if content is not None:
                found.append(eco)
                break
    return found


def fetch_lockfile_bundle(repo: RepoRef, ecosystem: str) -> dict[str, str]:
    """Fetch lockfiles for an ecosystem. Returns {filename: content} dict.

    Tries files in priority order, grabs the first one found plus any companions
    (e.g. pyproject.toml alongside uv.lock). Returns empty dict if nothing found.
    """
    entries = _LOCKFILE_MAP.get(ecosystem, [])

    for entry in entries:
        filename = entry["file"]
        content = fetch_file(repo, filename)
        if content is None:
            continue

        # Got the lockfile — now fetch companions
        bundle: dict[str, str] = {filename: content}
        for companion in entry["companions"]:
            comp_content = fetch_file(repo, companion)
            if comp_content is not None:
                bundle[companion] = comp_content

        return bundle

    return {}
