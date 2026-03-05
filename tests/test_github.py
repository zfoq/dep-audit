"""Tests for GitHub remote fetching."""

from dep_audit.github import (
    RepoRef,
    fetch_file,
    fetch_lockfile_bundle,
    is_github_target,
    parse_github_url,
)

# --- URL parsing ---


def test_parse_full_https_url():
    r = parse_github_url("https://github.com/fastapi/fastapi")
    assert r is not None
    assert r.owner == "fastapi"
    assert r.repo == "fastapi"
    assert r.ref == "HEAD"


def test_parse_url_with_git_suffix():
    r = parse_github_url("https://github.com/fastapi/fastapi.git")
    assert r is not None
    assert r.repo == "fastapi"


def test_parse_url_with_trailing_slash():
    r = parse_github_url("https://github.com/pallets/flask/")
    assert r is not None
    assert r.owner == "pallets"
    assert r.repo == "flask"


def test_parse_without_scheme():
    r = parse_github_url("github.com/owner/repo")
    assert r is not None
    assert r.owner == "owner"
    assert r.repo == "repo"


def test_parse_shorthand():
    r = parse_github_url("fastapi/fastapi")
    assert r is not None
    assert r.owner == "fastapi"
    assert r.repo == "fastapi"


def test_parse_shorthand_with_dots():
    r = parse_github_url("some.org/my-project")
    assert r is not None
    assert r.owner == "some.org"
    assert r.repo == "my-project"


def test_parse_local_path_returns_none():
    assert parse_github_url(".") is None
    assert parse_github_url("./relative") is None
    assert parse_github_url("/absolute/path") is None
    assert parse_github_url("../parent") is None


def test_parse_single_word_returns_none():
    assert parse_github_url("justoneword") is None


# --- is_github_target ---


def test_is_github_target_true():
    assert is_github_target("fastapi/fastapi") is True
    assert is_github_target("https://github.com/psf/requests") is True
    assert is_github_target("github.com/django/django") is True


def test_is_github_target_false():
    assert is_github_target(".") is False
    assert is_github_target("/home/user/project") is False
    assert is_github_target("./my-project") is False


# --- fetch_file (mocked) ---


def test_fetch_file_returns_content(monkeypatch):
    """fetch_file should return content from the HTTP response."""
    repo = RepoRef(owner="test", repo="proj", ref="main")

    class FakeResponse:
        def read(self):
            return b"hello world"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr("dep_audit.github.urllib.request.urlopen", lambda *a, **kw: FakeResponse())
    # Bypass cache
    monkeypatch.setattr("dep_audit.github.cache.get", lambda *a, **kw: None)
    monkeypatch.setattr("dep_audit.github.cache.put", lambda *a, **kw: None)

    result = fetch_file(repo, "pyproject.toml")
    assert result == "hello world"


def test_fetch_file_returns_none_on_404(monkeypatch):
    """fetch_file should return None for missing files."""
    import urllib.error

    repo = RepoRef(owner="test", repo="proj", ref="main")

    def raise_404(*a, **kw):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr("dep_audit.github.urllib.request.urlopen", raise_404)
    monkeypatch.setattr("dep_audit.github.cache.get", lambda *a, **kw: None)

    result = fetch_file(repo, "nonexistent.txt")
    assert result is None


def test_fetch_file_uses_cache(monkeypatch):
    """fetch_file should return cached content without hitting the network."""
    repo = RepoRef(owner="test", repo="proj", ref="HEAD")

    monkeypatch.setattr("dep_audit.github.cache.get", lambda *a, **kw: {"content": "cached!"})

    result = fetch_file(repo, "uv.lock")
    assert result == "cached!"


# --- fetch_lockfile_bundle (mocked) ---


def test_fetch_lockfile_bundle_priority(monkeypatch):
    """Should pick the first available lockfile and fetch companions."""
    repo = RepoRef(owner="test", repo="proj", ref="main")

    files = {
        "pyproject.toml": "[project]\nname = \"test\"\n",
        "requirements.txt": "requests==2.31.0\n",
    }

    def fake_fetch(r, path):
        return files.get(path)

    monkeypatch.setattr("dep_audit.github.fetch_file", fake_fetch)

    bundle = fetch_lockfile_bundle(repo, "python")
    # pyproject.toml should be found first (uv.lock and poetry.lock are missing)
    assert "pyproject.toml" in bundle
    # requirements.txt should NOT be in the bundle (pyproject.toml was found first)
    assert "requirements.txt" not in bundle


def test_fetch_lockfile_bundle_uv_lock_with_companion(monkeypatch):
    """When uv.lock is found, pyproject.toml should be fetched as companion."""
    repo = RepoRef(owner="test", repo="proj", ref="main")

    files = {
        "uv.lock": "version = 1\n[[package]]\nname = \"foo\"\nversion = \"1.0\"\n",
        "pyproject.toml": "[project]\nname = \"test\"\n",
    }

    def fake_fetch(r, path):
        return files.get(path)

    monkeypatch.setattr("dep_audit.github.fetch_file", fake_fetch)

    bundle = fetch_lockfile_bundle(repo, "python")
    assert "uv.lock" in bundle
    assert "pyproject.toml" in bundle


def test_fetch_lockfile_bundle_empty_when_nothing_found(monkeypatch):
    """Should return empty dict when no lockfiles exist."""
    repo = RepoRef(owner="test", repo="proj", ref="main")

    monkeypatch.setattr("dep_audit.github.fetch_file", lambda r, p: None)

    bundle = fetch_lockfile_bundle(repo, "python")
    assert bundle == {}
