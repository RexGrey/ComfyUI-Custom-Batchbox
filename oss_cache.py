"""
OSS Image Cache Module
======================

Provides image caching via Alibaba Cloud OSS to accelerate API requests.

Features:
- SHA-256 based image deduplication
- SQLite local cache database
- Automatic upload to OSS with transfer acceleration
- Safe degradation when OSS is not configured

Usage:
    from .oss_cache import oss_cache
    
    if oss_cache.is_enabled():
        url = oss_cache.get_or_upload(image_bytes, "image1.png")
"""

import os
import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from .batchbox_logger import logger

# Directory for this module
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_MODULE_DIR, "oss_cache.db")


def _compute_hash(data: bytes) -> str:
    """Compute SHA-256 hash of image bytes."""
    return hashlib.sha256(data).hexdigest()


def _guess_extension(filename: str, mime_type: str = "") -> str:
    """Guess file extension from filename or MIME type."""
    ext = Path(filename).suffix.lower()
    if ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
        return ext
    
    mime_map = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/webp': '.webp',
        'image/gif': '.gif',
        'image/bmp': '.bmp',
    }
    return mime_map.get(mime_type, '.png')


class CacheDB:
    """Thread-safe SQLite cache database for image URL mappings."""
    
    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        return self._local.conn
    
    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS image_cache (
                hash        TEXT PRIMARY KEY,
                oss_url     TEXT NOT NULL,
                oss_key     TEXT NOT NULL,
                file_size   INTEGER,
                uploaded_at DATETIME DEFAULT (datetime('now')),
                last_used   DATETIME DEFAULT (datetime('now')),
                use_count   INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_last_used ON image_cache(last_used);
        """)
        conn.commit()
    
    def get(self, file_hash: str) -> Optional[str]:
        """Look up cached URL by hash. Returns URL or None."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT oss_url FROM image_cache WHERE hash = ?",
            (file_hash,)
        ).fetchone()
        
        if row:
            # Update usage stats
            conn.execute(
                "UPDATE image_cache SET last_used = datetime('now'), use_count = use_count + 1 WHERE hash = ?",
                (file_hash,)
            )
            conn.commit()
            return row["oss_url"]
        return None
    
    def put(self, file_hash: str, oss_url: str, oss_key: str, file_size: int):
        """Store a new cache entry."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO image_cache 
               (hash, oss_url, oss_key, file_size, uploaded_at, last_used, use_count) 
               VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), 1)""",
            (file_hash, oss_url, oss_key, file_size)
        )
        conn.commit()
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(file_size) as total_size FROM image_cache"
        ).fetchone()
        return {
            "total_images": row["total"] or 0,
            "total_size_mb": round((row["total_size"] or 0) / 1024 / 1024, 2),
        }


class OSSImageCache:
    """
    Main OSS image caching class.
    
    Handles upload, caching, and URL generation for images,
    with safe degradation when OSS is not available.
    """
    
    def __init__(self):
        self._enabled = None  # Lazy init
        self._bucket = None
        self._config = None
        self._db = None
        self._init_lock = threading.Lock()
    
    def _load_config(self) -> Optional[Dict]:
        """Load OSS config from secrets.yaml."""
        try:
            import yaml
            secrets_path = os.path.join(_MODULE_DIR, "secrets.yaml")
            if not os.path.exists(secrets_path):
                return None
            
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f) or {}
            
            oss_config = secrets.get("oss")
            if not oss_config:
                return None
            
            # Validate required fields
            required = ['access_key_id', 'access_key_secret', 'bucket_name', 'endpoint', 'public_endpoint']
            for field in required:
                if not oss_config.get(field):
                    logger.warning(f"[OSSCache] Missing required field: oss.{field}")
                    return None
            
            return oss_config
        except Exception as e:
            logger.warning(f"[OSSCache] Failed to load config: {e}")
            return None
    
    def _ensure_initialized(self) -> bool:
        """Lazy initialization of OSS client and cache DB."""
        if self._enabled is not None:
            return self._enabled
        
        with self._init_lock:
            # Double-check after acquiring lock
            if self._enabled is not None:
                return self._enabled
            
            self._enabled = False
            
            # Check if oss2 is installed
            try:
                import oss2
            except ImportError:
                logger.info("[OSSCache] oss2 not installed. Run: pip install oss2")
                logger.info("[OSSCache] OSS caching disabled, using fallback multipart upload.")
                return False
            
            # Load config
            self._config = self._load_config()
            if not self._config:
                logger.info("[OSSCache] OSS not configured in secrets.yaml. Caching disabled.")
                return False
            
            # Initialize OSS bucket
            try:
                auth = oss2.Auth(
                    self._config['access_key_id'],
                    self._config['access_key_secret']
                )
                self._bucket = oss2.Bucket(
                    auth,
                    self._config['endpoint'],
                    self._config['bucket_name']
                )
                
                # Quick connectivity test (list up to 1 object)
                self._bucket.list_objects(max_keys=1)
                
                logger.info(f"[OSSCache] ✅ Connected to OSS: {self._config['bucket_name']}")
                logger.info(f"[OSSCache]    Upload endpoint: {self._config['endpoint']}")
                logger.info(f"[OSSCache]    Public endpoint: {self._config['public_endpoint']}")
            except Exception as e:
                logger.error(f"[OSSCache] ❌ Failed to connect to OSS: {e}")
                return False
            
            # Initialize cache database
            try:
                self._db = CacheDB()
                stats = self._db.get_stats()
                logger.info(f"[OSSCache]    Cache: {stats['total_images']} images, {stats['total_size_mb']} MB")
            except Exception as e:
                logger.error(f"[OSSCache] ❌ Failed to init cache DB: {e}")
                return False
            
            self._enabled = True
            return True
    
    def is_enabled(self) -> bool:
        """Check if OSS caching is available and configured."""
        return self._ensure_initialized()
    
    def get_or_upload(self, image_bytes: bytes, filename: str = "image.png", 
                       mime_type: str = "image/png") -> Optional[str]:
        """
        Get cached URL or upload image to OSS.
        
        Args:
            image_bytes: Raw image data
            filename: Original filename (for extension detection)
            mime_type: MIME type of the image
            
        Returns:
            Public OSS URL, or None if upload fails
        """
        if not self._ensure_initialized():
            return None
        
        import oss2
        
        # 1. Compute hash
        file_hash = _compute_hash(image_bytes)
        
        # 2. Check cache
        cached_url = self._db.get(file_hash)
        if cached_url:
            logger.info(f"[OSSCache] ✅ Cache hit: {file_hash[:12]}... (saved upload)")
            return cached_url
        
        # 3. Upload to OSS
        ext = _guess_extension(filename, mime_type)
        oss_key = f"images/{file_hash[:2]}/{file_hash[2:4]}/{file_hash}{ext}"
        
        try:
            file_size = len(image_bytes)
            start_time = time.time()
            
            if file_size > 10 * 1024 * 1024:  # > 10MB: use resumable upload via temp file
                logger.info(f"[OSSCache] ⬆️ Uploading large image ({file_size/1024/1024:.1f}MB): {oss_key}")
                import tempfile
                # Write to temp file for resumable upload (supports resume on network failure)
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                        tmp.write(image_bytes)
                        tmp_path = tmp.name
                    oss2.resumable_upload(
                        self._bucket, oss_key, tmp_path,
                        multipart_threshold=10 * 1024 * 1024,
                        part_size=5 * 1024 * 1024,
                        num_threads=3
                    )
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
            else:
                logger.info(f"[OSSCache] ⬆️ Uploading image ({file_size/1024:.0f}KB): {oss_key}")
                self._bucket.put_object(oss_key, image_bytes)
            
            elapsed = time.time() - start_time
            
            # Build public URL (not using accelerate endpoint for reading)
            public_url = (
                f"https://{self._config['bucket_name']}"
                f".{self._config['public_endpoint']}"
                f"/{oss_key}"
            )
            
            # 4. Store in cache
            self._db.put(file_hash, public_url, oss_key, file_size)
            
            logger.info(f"[OSSCache] ✅ Upload complete ({elapsed:.1f}s): {public_url}")
            return public_url
            
        except Exception as e:
            logger.error(f"[OSSCache] ❌ Upload failed: {e}")
            return None
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        if not self._ensure_initialized():
            return {"enabled": False}
        stats = self._db.get_stats()
        stats["enabled"] = True
        return stats


# Global singleton instance
oss_cache = OSSImageCache()
