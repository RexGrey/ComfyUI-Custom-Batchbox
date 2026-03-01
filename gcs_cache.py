"""
GCS Image Cache Module
======================

Provides image caching via Google Cloud Storage for Gemini API endpoints.
Images uploaded to GCS can be referenced via gs:// URIs in file_data.file_uri,
which is natively supported by Gemini API (both Vertex AI and AI Studio).

Features:
- SHA-256 based image deduplication (shared with OSS cache)
- Upload to GCS with resumable upload for large files
- Returns gs:// URI for use in Gemini API requests
- Graceful fallback when GCS is not configured
"""

import os
import hashlib
import time
import threading
import sqlite3
from typing import Optional, Dict

from .batchbox_logger import logger

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_MODULE_DIR, "gcs_cache.db")


def _compute_hash(data: bytes) -> str:
    """Compute SHA-256 hash of image bytes."""
    return hashlib.sha256(data).hexdigest()


def _guess_extension(filename: str, mime_type: str = "") -> str:
    """Guess file extension from filename or MIME type."""
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    # Try from filename
    _, ext = os.path.splitext(filename)
    if ext:
        return ext.lower()
    # Try from MIME type
    return ext_map.get(mime_type, ".png")


class GCSCacheDB:
    """Thread-safe SQLite cache database for GCS URI mappings."""

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
            CREATE TABLE IF NOT EXISTS gcs_cache (
                file_hash TEXT PRIMARY KEY,
                gs_uri TEXT NOT NULL,
                gcs_path TEXT NOT NULL,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    def get(self, file_hash: str) -> Optional[str]:
        """Look up cached gs:// URI by hash."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT gs_uri FROM gcs_cache WHERE file_hash = ?",
            (file_hash,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def put(self, file_hash: str, gs_uri: str, gcs_path: str, file_size: int):
        """Store a new cache entry."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO gcs_cache (file_hash, gs_uri, gcs_path, file_size) VALUES (?, ?, ?, ?)",
            (file_hash, gs_uri, gcs_path, file_size)
        )
        conn.commit()

    def get_stats(self) -> Dict:
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM gcs_cache")
        count, total_size = cursor.fetchone()
        return {"count": count, "total_size": total_size}


class GCSImageCache:
    """
    GCS image cache for Gemini API.
    
    Uploads images to Google Cloud Storage and returns gs:// URIs
    for use in Gemini API's file_data.file_uri field.
    """

    def __init__(self):
        self._enabled = None  # Lazy init
        self._client = None
        self._bucket = None
        self._config = None
        self._db = None

    def _load_config(self) -> Optional[Dict]:
        """Load GCS config from secrets.yaml."""
        try:
            import yaml
            secrets_path = os.path.join(_MODULE_DIR, "secrets.yaml")
            if not os.path.exists(secrets_path):
                return None

            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f) or {}

            gcs_config = secrets.get("gcs")
            if not gcs_config:
                return None

            # Validate required fields
            if not gcs_config.get("bucket_name"):
                logger.warning("[GCSCache] Missing required field: gcs.bucket_name")
                return None

            return gcs_config
        except Exception as e:
            logger.warning(f"[GCSCache] Failed to load config: {e}")
            return None

    def _ensure_initialized(self) -> bool:
        """Lazy initialization of GCS client and cache DB."""
        if self._enabled is not None:
            return self._enabled

        self._config = self._load_config()
        if not self._config:
            self._enabled = False
            logger.info("[GCSCache] GCS caching disabled (no config in secrets.yaml)")
            return False

        try:
            from google.cloud import storage
        except ImportError:
            self._enabled = False
            logger.info("[GCSCache] google-cloud-storage not installed. Run: pip install google-cloud-storage")
            return False

        try:
            bucket_name = self._config["bucket_name"]
            credentials_path = self._config.get("credentials_path", "")

            # Set credentials if path provided
            if credentials_path:
                abs_path = credentials_path if os.path.isabs(credentials_path) else os.path.join(_MODULE_DIR, credentials_path)
                if os.path.exists(abs_path):
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
                else:
                    logger.warning(f"[GCSCache] Credentials file not found: {abs_path}")
                    self._enabled = False
                    return False

            self._client = storage.Client()
            self._bucket = self._client.bucket(bucket_name)

            # Verify bucket exists
            if not self._bucket.exists():
                logger.warning(f"[GCSCache] Bucket '{bucket_name}' does not exist")
                self._enabled = False
                return False

            self._db = GCSCacheDB()
            self._enabled = True

            stats = self._db.get_stats()
            logger.info(f"[GCSCache] ✅ Connected to GCS: {bucket_name}")
            logger.info(f"[GCSCache]    Cache: {stats['count']} images, {stats['total_size']/1024/1024:.2f} MB")
            return True

        except Exception as e:
            logger.warning(f"[GCSCache] Failed to initialize: {e}")
            self._enabled = False
            return False

    def is_enabled(self) -> bool:
        return self._ensure_initialized()

    def get_or_upload(self, image_bytes: bytes, filename: str = "image.png",
                      mime_type: str = "image/png") -> Optional[str]:
        """
        Get cached gs:// URI or upload image to GCS.
        
        Returns:
            gs:// URI string, or None if upload fails
        """
        if not self._ensure_initialized():
            return None

        # 1. Compute hash
        file_hash = _compute_hash(image_bytes)

        # 2. Check cache
        cached_uri = self._db.get(file_hash)
        if cached_uri:
            logger.info(f"[GCSCache] ✅ Cache hit: {file_hash[:12]}... (saved upload)")
            return cached_uri

        # 3. Upload to GCS
        ext = _guess_extension(filename, mime_type)
        prefix = self._config.get("path_prefix", "images")
        gcs_path = f"{prefix}/{file_hash[:2]}/{file_hash[2:4]}/{file_hash}{ext}"

        try:
            file_size = len(image_bytes)
            start_time = time.time()

            logger.info(f"[GCSCache] ⬆️ Uploading image ({file_size/1024/1024:.1f}MB): gs://{self._config['bucket_name']}/{gcs_path}")

            blob = self._bucket.blob(gcs_path)
            blob.upload_from_string(image_bytes, content_type=mime_type)

            elapsed = time.time() - start_time

            # Build gs:// URI
            gs_uri = f"gs://{self._config['bucket_name']}/{gcs_path}"

            # 4. Store in cache
            self._db.put(file_hash, gs_uri, gcs_path, file_size)

            logger.info(f"[GCSCache] ✅ Upload complete ({elapsed:.1f}s): {gs_uri}")
            return gs_uri

        except Exception as e:
            logger.error(f"[GCSCache] ❌ Upload failed: {e}")
            return None

    def get_stats(self) -> Dict:
        if not self._ensure_initialized():
            return {"count": 0, "total_size": 0}
        return self._db.get_stats()


# Global singleton
gcs_cache = GCSImageCache()
