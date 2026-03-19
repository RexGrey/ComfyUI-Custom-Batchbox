"""
Tests for gcs_cache.py

Covers: _compute_hash, _guess_extension, GCSCacheDB (CRUD + stats), GCSImageCache logic.
"""

import importlib
import os
import hashlib
from unittest.mock import patch, MagicMock

import pytest

_pkg = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_mod = importlib.import_module(f"{_pkg}.gcs_cache")

_compute_hash = _mod._compute_hash
_guess_extension = _mod._guess_extension
GCSCacheDB = _mod.GCSCacheDB


# ──────────────────────────────────────────────────────────────────────────────
# _compute_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeHash:

    def test_deterministic(self):
        assert _compute_hash(b"data") == _compute_hash(b"data")

    def test_sha256(self):
        data = b"gcs test"
        assert _compute_hash(data) == hashlib.sha256(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# _guess_extension
# ──────────────────────────────────────────────────────────────────────────────

class TestGuessExtension:

    def test_from_filename(self):
        assert _guess_extension("photo.jpg") == ".jpg"

    def test_from_mime(self):
        assert _guess_extension("noext", "image/webp") == ".webp"

    def test_default(self):
        assert _guess_extension("noext") == ".png"


# ──────────────────────────────────────────────────────────────────────────────
# GCSCacheDB
# ──────────────────────────────────────────────────────────────────────────────

class TestGCSCacheDB:

    def test_put_and_get(self, tmp_db_path):
        db = GCSCacheDB(db_path=tmp_db_path)
        db.put("hash1", "gs://bucket/path.png", "path.png", 2048)
        assert db.get("hash1") == "gs://bucket/path.png"

    def test_get_missing(self, tmp_db_path):
        db = GCSCacheDB(db_path=tmp_db_path)
        assert db.get("missing") is None

    def test_put_replaces(self, tmp_db_path):
        db = GCSCacheDB(db_path=tmp_db_path)
        db.put("h1", "gs://old", "old.png", 100)
        db.put("h1", "gs://new", "new.png", 200)
        assert db.get("h1") == "gs://new"

    def test_get_stats_empty(self, tmp_db_path):
        db = GCSCacheDB(db_path=tmp_db_path)
        stats = db.get_stats()
        assert stats["count"] == 0
        assert stats["total_size"] == 0

    def test_get_stats_with_data(self, tmp_db_path):
        db = GCSCacheDB(db_path=tmp_db_path)
        db.put("h1", "gs://b/1", "1.png", 1000)
        db.put("h2", "gs://b/2", "2.png", 2000)
        stats = db.get_stats()
        assert stats["count"] == 2
        assert stats["total_size"] == 3000


# ──────────────────────────────────────────────────────────────────────────────
# GCSImageCache
# ──────────────────────────────────────────────────────────────────────────────

class TestGCSImageCache:

    def test_disabled_when_no_config(self):
        cache = _mod.GCSImageCache()
        with patch.object(cache, "_load_config", return_value=None):
            assert cache.is_enabled() is False

    def test_get_or_upload_returns_none_when_disabled(self):
        cache = _mod.GCSImageCache()
        cache._enabled = False
        assert cache.get_or_upload(b"data") is None

    def test_get_stats_when_disabled(self):
        cache = _mod.GCSImageCache()
        cache._enabled = False
        stats = cache.get_stats()
        assert stats == {"count": 0, "total_size": 0}
