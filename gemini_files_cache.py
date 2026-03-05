"""
Google Gemini Files API Cache
==============================

Uploads images to Google's Files API (generativelanguage.googleapis.com)
and returns file_uri for use in generateContent requests.

Key advantages over GCS:
- Uses the same API key as AI Studio (no separate credentials needed)
- Files cached for 48 hours on Google's servers
- file_uri natively supported by generateContent
- SHA-256 dedup avoids re-uploading identical images

Usage:
    from .gemini_files_cache import gemini_files_cache
    file_uri = gemini_files_cache.get_or_upload(api_key, image_bytes, "image.png", "image/png")
"""

import hashlib
import time
import threading
import sqlite3
import os
import io
from typing import Optional, Dict, Tuple

import requests

from .batchbox_logger import logger

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_MODULE_DIR, "gemini_files_cache.db")
_FILES_API_BASE = "https://generativelanguage.googleapis.com"


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GeminiFilesCacheDB:
    """SQLite cache mapping image hash → file_uri (with 48h expiry)."""

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files_cache (
                file_hash TEXT PRIMARY KEY,
                file_uri TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                file_size INTEGER,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.commit()

    def get(self, file_hash: str) -> Optional[str]:
        """Get cached file_uri if not expired."""
        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute(
            "SELECT file_uri FROM files_cache WHERE file_hash = ? AND expires_at > ?",
            (file_hash, now)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def put(self, file_hash: str, file_uri: str, file_name: str,
            mime_type: str, file_size: int, ttl_hours: float = 47):
        """Store cache entry with TTL (default 47h, slightly less than 48h to be safe)."""
        now = time.time()
        expires_at = now + ttl_hours * 3600
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO files_cache 
               (file_hash, file_uri, file_name, mime_type, file_size, created_at, expires_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_hash, file_uri, file_name, mime_type, file_size, now, expires_at)
        )
        conn.commit()

    def cleanup_expired(self):
        """Remove expired entries."""
        conn = self._get_conn()
        conn.execute("DELETE FROM files_cache WHERE expires_at <= ?", (time.time(),))
        conn.commit()

    def get_stats(self) -> Dict:
        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM files_cache WHERE expires_at > ?",
            (now,)
        )
        count, total_size = cursor.fetchone()
        return {"count": count, "total_size": total_size}


class GeminiFilesCache:
    """
    Uploads images to Google's Files API for use in Gemini generateContent.
    
    Flow:
    1. Hash image bytes → check local SQLite cache
    2. If cache miss → upload to Files API → get file_uri
    3. Return file_uri for use in file_data.file_uri
    """

    def __init__(self):
        self._db = None
        self._initialized = False
        self._upload_locks = {}  # Per-hash locks to prevent parallel duplicate uploads
        self._locks_lock = threading.Lock()  # Lock for the locks dict

    def _ensure_db(self):
        if not self._initialized:
            self._db = GeminiFilesCacheDB()
            self._db.cleanup_expired()
            stats = self._db.get_stats()
            logger.info(f"[FilesAPI] Cache: {stats['count']} files, {stats['total_size']/1024/1024:.2f} MB")
            self._initialized = True

    def get_or_upload(self, api_key: str, image_bytes: bytes,
                      filename: str = "image.png",
                      mime_type: str = "image/png") -> Optional[str]:
        """
        Get cached file_uri or upload image to Google Files API.
        
        Args:
            api_key: Google API key (same as used for generateContent)
            image_bytes: Raw image bytes
            filename: Display name for the file
            mime_type: MIME type of the image
            
        Returns:
            file_uri string for use in file_data, or None if upload fails
        """
        self._ensure_db()

        # 1. Check cache (fast path, no lock needed)
        file_hash = _compute_hash(image_bytes)
        cached_uri = self._db.get(file_hash)
        if cached_uri:
            logger.info(f"[FilesAPI] ✅ Cache hit: {file_hash[:12]}... (saved upload)")
            return cached_uri

        # 2. Acquire per-hash lock to prevent parallel duplicate uploads
        # If 3 batches try to upload the same image, only 1 actually uploads.
        with self._locks_lock:
            if file_hash not in self._upload_locks:
                self._upload_locks[file_hash] = threading.Lock()
            upload_lock = self._upload_locks[file_hash]

        with upload_lock:
            # Re-check cache after acquiring lock (another thread may have uploaded)
            cached_uri = self._db.get(file_hash)
            if cached_uri:
                logger.info(f"[FilesAPI] ✅ Cache hit (after wait): {file_hash[:12]}... (saved upload)")
                return cached_uri

            # Actually upload
            return self._do_upload(api_key, image_bytes, file_hash, filename, mime_type)

    def _do_upload(self, api_key: str, image_bytes: bytes,
                    file_hash: str, filename: str, mime_type: str) -> Optional[str]:
        """Perform the actual upload to Google Files API."""
        file_size = len(image_bytes)
        logger.info(f"[FilesAPI] ⬆️ Uploading image ({file_size/1024/1024:.1f}MB) to Google Files API...")

        try:
            start_time = time.time()

            # Step A: Start resumable upload
            init_url = f"{_FILES_API_BASE}/upload/v1beta/files"
            init_headers = {
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(file_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            }
            init_body = {
                "file": {
                    "display_name": f"{file_hash[:16]}_{filename}"
                }
            }

            init_resp = requests.post(
                init_url,
                headers=init_headers,
                json=init_body,
                params={"key": api_key},
                timeout=30,
            )

            if init_resp.status_code != 200:
                logger.error(f"[FilesAPI] ❌ Init failed: HTTP {init_resp.status_code}: {init_resp.text[:200]}")
                return None

            # Get upload URL from response headers
            upload_url = init_resp.headers.get("X-Goog-Upload-URL")
            if not upload_url:
                upload_url = init_resp.headers.get("x-goog-upload-url")
            if not upload_url:
                logger.error(f"[FilesAPI] ❌ No upload URL in response headers: {dict(init_resp.headers)}")
                return None

            # Step B: Upload the actual bytes
            upload_headers = {
                "Content-Length": str(file_size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            }

            upload_resp = requests.post(
                upload_url,
                headers=upload_headers,
                data=image_bytes,
                timeout=120,
            )

            if upload_resp.status_code != 200:
                logger.error(f"[FilesAPI] ❌ Upload failed: HTTP {upload_resp.status_code}: {upload_resp.text[:200]}")
                return None

            # Parse response to get file_uri
            result = upload_resp.json()
            file_info = result.get("file", {})
            file_uri = file_info.get("uri")

            if not file_uri:
                logger.error(f"[FilesAPI] ❌ No file_uri in response: {result}")
                return None

            elapsed = time.time() - start_time

            # Cache the result
            file_name = file_info.get("name", "")
            self._db.put(file_hash, file_uri, file_name, mime_type, file_size)

            logger.info(f"[FilesAPI] ✅ Upload complete ({elapsed:.1f}s): {file_uri}")
            return file_uri

        except requests.exceptions.Timeout:
            logger.error("[FilesAPI] ❌ Upload timed out")
            return None
        except Exception as e:
            logger.error(f"[FilesAPI] ❌ Upload failed: {e}")
            return None

    def get_stats(self) -> Dict:
        self._ensure_db()
        return self._db.get_stats()


# Global singleton
gemini_files_cache = GeminiFilesCache()
