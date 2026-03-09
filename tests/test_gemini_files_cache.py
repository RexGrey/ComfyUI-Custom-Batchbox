"""
Tests for gemini_files_cache.py

Covers: _compute_hash, GeminiFilesCacheDB (CRUD + TTL expiry + cleanup + stats),
        GeminiFilesCache logic (get_or_upload, _do_upload).
"""

import importlib
import os
import time
import hashlib
from unittest.mock import patch, MagicMock, Mock

import pytest

_pkg = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_mod = importlib.import_module(f"{_pkg}.gemini_files_cache")

_compute_hash = _mod._compute_hash
GeminiFilesCacheDB = _mod.GeminiFilesCacheDB
GeminiFilesCache = _mod.GeminiFilesCache


# ──────────────────────────────────────────────────────────────────────────────
# _compute_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeHash:

    def test_deterministic(self):
        assert _compute_hash(b"gemini") == _compute_hash(b"gemini")

    def test_sha256(self):
        data = b"files api"
        assert _compute_hash(data) == hashlib.sha256(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# GeminiFilesCacheDB
# ──────────────────────────────────────────────────────────────────────────────

class TestGeminiFilesCacheDB:

    def test_put_and_get(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        db.put("hash1", "files/abc123", "files/abc123", "image/png", 1024)
        assert db.get("hash1") == "files/abc123"

    def test_get_missing(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        assert db.get("nonexistent") is None

    def test_get_expired(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        # Insert with TTL of 0 hours (already expired)
        db.put("hash_exp", "files/expired", "files/expired", "image/png", 100, ttl_hours=0)
        # Sleep tiny bit to ensure expiry
        time.sleep(0.01)
        assert db.get("hash_exp") is None

    def test_get_not_expired(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        db.put("hash_ok", "files/valid", "files/valid", "image/png", 100, ttl_hours=1)
        assert db.get("hash_ok") == "files/valid"

    def test_cleanup_expired(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        # One expired, one valid
        db.put("expired", "uri1", "name1", "image/png", 100, ttl_hours=0)
        db.put("valid", "uri2", "name2", "image/png", 200, ttl_hours=24)
        time.sleep(0.01)
        db.cleanup_expired()
        assert db.get("expired") is None
        assert db.get("valid") == "uri2"

    def test_get_stats_excludes_expired(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        db.put("exp", "uri1", "n1", "image/png", 500, ttl_hours=0)
        db.put("ok", "uri2", "n2", "image/jpeg", 1000, ttl_hours=24)
        time.sleep(0.01)
        stats = db.get_stats()
        assert stats["count"] == 1
        assert stats["total_size"] == 1000

    def test_get_stats_empty(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        stats = db.get_stats()
        assert stats["count"] == 0
        assert stats["total_size"] == 0

    def test_put_replaces(self, tmp_db_path):
        db = GeminiFilesCacheDB(db_path=tmp_db_path)
        db.put("h1", "uri_old", "name_old", "image/png", 100)
        db.put("h1", "uri_new", "name_new", "image/jpeg", 200)
        assert db.get("h1") == "uri_new"


# ──────────────────────────────────────────────────────────────────────────────
# GeminiFilesCache
# ──────────────────────────────────────────────────────────────────────────────

class TestGeminiFilesCache:

    def test_ensure_db_initializes_once(self, tmp_db_path):
        cache = GeminiFilesCache()
        with patch.object(_mod, "GeminiFilesCacheDB", return_value=MagicMock()) as mock_cls:
            mock_cls.return_value.get_stats.return_value = {"count": 0, "total_size": 0}
            mock_cls.return_value.cleanup_expired = MagicMock()
            cache._ensure_db()
            cache._ensure_db()  # Second call should not re-init
            mock_cls.assert_called_once()

    def test_get_or_upload_cache_hit(self, tmp_db_path):
        cache = GeminiFilesCache()
        mock_db = MagicMock()
        mock_db.get_stats.return_value = {"count": 1, "total_size": 100}
        mock_db.get.return_value = "files/cached_uri"
        cache._db = mock_db
        cache._initialized = True

        result = cache.get_or_upload("api_key", b"image data")
        assert result == "files/cached_uri"

    @patch.object(_mod, "requests")
    def test_do_upload_success(self, mock_requests):
        cache = GeminiFilesCache()
        mock_db = MagicMock()
        mock_db.get_stats.return_value = {"count": 0, "total_size": 0}
        mock_db.get.return_value = None
        cache._db = mock_db
        cache._initialized = True

        # Mock init response
        init_resp = Mock()
        init_resp.status_code = 200
        init_resp.headers = {"X-Goog-Upload-URL": "https://upload.example.com/upload123"}

        # Mock upload response
        upload_resp = Mock()
        upload_resp.status_code = 200
        upload_resp.json.return_value = {
            "file": {
                "uri": "files/generated_uri",
                "name": "files/abc123"
            }
        }

        mock_requests.post.side_effect = [init_resp, upload_resp]

        result = cache._do_upload("api_key", b"img", "hash123", "image.png", "image/png")
        assert result == "files/generated_uri"
        mock_db.put.assert_called_once()

    @patch.object(_mod, "requests")
    def test_do_upload_init_fails(self, mock_requests):
        cache = GeminiFilesCache()
        cache._db = MagicMock()
        cache._initialized = True

        init_resp = Mock()
        init_resp.status_code = 400
        init_resp.text = "Bad request"
        mock_requests.post.return_value = init_resp

        result = cache._do_upload("key", b"img", "h", "f.png", "image/png")
        assert result is None

    @patch.object(_mod, "requests")
    def test_do_upload_no_upload_url(self, mock_requests):
        cache = GeminiFilesCache()
        cache._db = MagicMock()
        cache._initialized = True

        init_resp = Mock()
        init_resp.status_code = 200
        init_resp.headers = {}  # No upload URL
        mock_requests.post.return_value = init_resp

        result = cache._do_upload("key", b"img", "h", "f.png", "image/png")
        assert result is None

    @patch.object(_mod, "requests")
    def test_do_upload_timeout(self, mock_requests):
        import requests as real_requests
        cache = GeminiFilesCache()
        cache._db = MagicMock()
        cache._initialized = True

        mock_requests.post.side_effect = real_requests.exceptions.Timeout("timed out")
        mock_requests.exceptions = real_requests.exceptions

        result = cache._do_upload("key", b"img", "h", "f.png", "image/png")
        assert result is None

    def test_get_stats(self, tmp_db_path):
        cache = GeminiFilesCache()
        mock_db = MagicMock()
        mock_db.get_stats.return_value = {"count": 5, "total_size": 5000}
        mock_db.cleanup_expired = MagicMock()
        cache._db = mock_db
        cache._initialized = True

        stats = cache.get_stats()
        assert stats["count"] == 5
