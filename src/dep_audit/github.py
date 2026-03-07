"""Fetch lockfiles from public GitHub repos via raw.githubusercontent.com.

Uses urllib.request (stdlib) — same approach as depsdev.py.
Responses are cached so repeated scans of the same repo don't re-download.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from dep_audit import cache

logger = logging.getLogger("dep_audit")

_RAW_BASE = "https://raw.githubusercontent.com"
_TTL_REMOTE = 3600  # 1 hour — lockfiles don't change that often


@dataclass
class RepoRef:
    owner: str
    repo: str
    ref: str = "HEAD"


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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
            cache.put("github", cache_key, {"content": content})
            return content
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and attempt < 2:
                delay = (1.0, 3.0)[attempt]
                logger.debug("Rate limited by GitHub, retrying in %.0fs...", delay)
                time.sleep(delay)
                continue
            return None
        except (urllib.error.URLError, OSError):
            return None
    return None


def fetch_lockfile_bundle(repo: RepoRef, ecosystem: str) -> dict[str, str]:
    """Fetch lockfiles for an ecosystem. Returns {filename: content} dict.

    Tries files in priority order, grabs the first one found plus any companions
    (e.g. pyproject.toml alongside uv.lock). Returns empty dict if nothing found.
    """
    from dep_audit import ecosystems

    eco = ecosystems.get_or_none(ecosystem)
    if eco is None:
        return {}

    for spec in eco.lockfiles:
        content = fetch_file(repo, spec.file)
        if content is None:
            continue

        # Got the lockfile — now fetch companions
        bundle: dict[str, str] = {spec.file: content}
        for companion in spec.companions:
            comp_content = fetch_file(repo, companion)
            if comp_content is not None:
                bundle[companion] = comp_content

        return bundle

    return {}


def fetch_all_lockfile_bundles(repo: RepoRef) -> dict[str, dict[str, str]]:
    """Detect all ecosystems present by attempting lockfile fetches in priority order.

    Returns {ecosystem_name: bundle} for every ecosystem whose lockfiles are found.
    Avoids the double-fetch problem of detect_remote_ecosystem + fetch_lockfile_bundle.
    """
    from dep_audit import ecosystems

    result: dict[str, dict[str, str]] = {}
    for eco in ecosystems.all_ecosystems():
        bundle = fetch_lockfile_bundle(repo, eco.name)
        if bundle:
            result[eco.name] = bundle
    return result
