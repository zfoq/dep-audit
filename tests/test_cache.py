"""Tests for the file-based cache."""

from unittest.mock import patch

from dep_audit import cache


def test_put_and_get(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        cache.put("test", "key1", {"hello": "world"})
        result = cache.get("test", "key1")
        assert result == {"hello": "world"}


def test_get_missing(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        result = cache.get("test", "nonexistent")
        assert result is None


def test_get_expired(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        cache.put("test", "key1", {"data": True})
        # Expired with 0 TTL
        result = cache.get("test", "key1", ttl=0)
        assert result is None


def test_clear(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        cache.put("test", "key1", {"data": True})
        cache.put("test", "key2", {"data": True})
        cache.clear()
        assert cache.get("test", "key1") is None
        assert cache.get("test", "key2") is None


def test_stats(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        cache.put("test", "key1", {"data": True})
        cache.put("test", "key2", {"more": "data"})
        s = cache.stats()
        assert s["entries"] == 2
        assert s["size_bytes"] > 0


def test_stats_empty(tmp_path):
    with patch.object(cache, "_DEFAULT_DIR", tmp_path / "cache"):
        s = cache.stats()
        assert s["entries"] == 0
        assert s["size_bytes"] == 0
