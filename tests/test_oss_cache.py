"""
Tests for oss_cache.py

Covers: _compute_hash, _guess_extension, CacheDB (CRUD + stats), OSSImageCache logic.
"""

import importlib
import os
import hashlib
from unittest.mock import patch, MagicMock

import pytest

# Import via package path for relative import support
_pkg = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_mod = importlib.import_module(f"{_pkg}.oss_cache")

_compute_hash = _mod._compute_hash
_guess_extension = _mod._guess_extension
CacheDB = _mod.CacheDB


# ──────────────────────────────────────────────────────────────────────────────
# _compute_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeHash:

    def test_deterministic(self):
        data = b"hello world"
        assert _compute_hash(data) == _compute_hash(data)

    def test_sha256(self):
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()
        assert _compute_hash(data) == expected

    def test_different_data(self):
        assert _compute_hash(b"aaa") != _compute_hash(b"bbb")

    def test_empty_bytes(self):
        result = _compute_hash(b"")
        assert len(result) == 64  # SHA-256 hex length


# ──────────────────────────────────────────────────────────────────────────────
# _guess_extension
# ──────────────────────────────────────────────────────────────────────────────

class TestGuessExtension:

    def test_png_filename(self):
        assert _guess_extension("image.png") == ".png"

    def test_jpeg_filename(self):
        assert _guess_extension("photo.jpg") == ".jpg"

    def test_webp_filename(self):
        assert _guess_extension("pic.webp") == ".webp"

    def test_mime_fallback(self):
        assert _guess_extension("noext", "image/jpeg") == ".jpg"

    def test_default_png(self):
        assert _guess_extension("noext", "") == ".png"

    def test_unknown_mime(self):
        assert _guess_extension("noext", "application/octet-stream") == ".png"


# ──────────────────────────────────────────────────────────────────────────────
# CacheDB
# ──────────────────────────────────────────────────────────────────────────────

class TestCacheDB:

    def test_put_and_get(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        db.put("abc123", "https://oss.example.com/img.png", "images/abc123.png", 1024)
        url = db.get("abc123")
        assert url == "https://oss.example.com/img.png"

    def test_get_missing(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        assert db.get("nonexistent") is None

    def test_put_updates_on_conflict(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        db.put("hash1", "url_old", "key_old", 100)
        db.put("hash1", "url_new", "key_new", 200)
        assert db.get("hash1") == "url_new"

    def test_get_increments_use_count(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        db.put("hash1", "url1", "key1", 500)
        # First get increments to 2
        db.get("hash1")
        # Second get increments to 3
        db.get("hash1")
        conn = db._get_conn()
        row = conn.execute("SELECT use_count FROM image_cache WHERE hash = ?", ("hash1",)).fetchone()
        assert row[0] == 3  # 1 initial + 2 gets

    def test_get_stats_empty(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        stats = db.get_stats()
        assert stats["total_images"] == 0
        assert stats["total_size_mb"] == 0

    def test_get_stats_with_data(self, tmp_db_path):
        db = CacheDB(db_path=tmp_db_path)
        db.put("h1", "url1", "k1", 1024 * 1024)  # 1MB
        db.put("h2", "url2", "k2", 2 * 1024 * 1024)  # 2MB
        stats = db.get_stats()
        assert stats["total_images"] == 2
        assert stats["total_size_mb"] == 3.0


# ──────────────────────────────────────────────────────────────────────────────
# OSSImageCache
# ──────────────────────────────────────────────────────────────────────────────

class TestOSSImageCache:

    def test_disabled_when_no_config(self):
        cache = _mod.OSSImageCache()
        with patch.object(cache, "_load_config", return_value=None):
            assert cache.is_enabled() is False

    def test_disabled_when_no_oss2(self):
        cache = _mod.OSSImageCache()
        with patch.object(cache, "_load_config", return_value={"endpoint": "x"}), \
             patch.dict("sys.modules", {"oss2": None}):
            # oss2 import will raise ImportError when module is None
            cache._enabled = None  # Reset
            assert cache.is_enabled() is False

    def test_get_or_upload_returns_none_when_disabled(self):
        cache = _mod.OSSImageCache()
        cache._enabled = False
        result = cache.get_or_upload(b"image data")
        assert result is None

    def test_get_stats_when_disabled(self):
        cache = _mod.OSSImageCache()
        cache._enabled = False
        stats = cache.get_stats()
        assert stats == {"enabled": False}
