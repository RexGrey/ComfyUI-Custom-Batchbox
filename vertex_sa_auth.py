"""
Vertex AI Service Account Authentication
=========================================

Generates OAuth2 access tokens from Google Service Account JSON files
for Vertex AI API authentication. Tokens are cached and auto-refreshed.

Usage:
    from .vertex_sa_auth import get_access_token
    token = get_access_token("/path/to/sa.json")
    # token is a ya29.xxx string valid for ~1 hour

Multiple JSON files can be used; tokens are cached per-file.
Thread-safe.
"""

import os
import time
import threading
from typing import Optional

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Cache: {json_path: (credentials_object, expiry_timestamp)}
_token_cache = {}
_lock = threading.Lock()

# Refresh tokens 5 minutes before they expire
_REFRESH_MARGIN = 300


def get_access_token(json_path: str) -> Optional[str]:
    """
    Get a valid OAuth2 access token from a Service Account JSON file.
    
    Caches the credential and auto-refreshes when expired.
    Returns None if the file is missing or the library is unavailable.
    """
    abs_path = _resolve_path(json_path)

    with _lock:
        if abs_path in _token_cache:
            creds = _token_cache[abs_path]
            if creds.valid and creds.expiry and creds.expiry.timestamp() > time.time() + _REFRESH_MARGIN:
                return creds.token

    # Build or refresh credentials outside the lock (network I/O)
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        with _lock:
            if abs_path in _token_cache:
                creds = _token_cache[abs_path]
            else:
                if not os.path.exists(abs_path):
                    print(f"[VertexSA] ❌ JSON file not found: {abs_path}")
                    return None
                creds = service_account.Credentials.from_service_account_file(
                    abs_path, scopes=_SCOPES
                )
                _token_cache[abs_path] = creds

        # Refresh (this is the network call to get ya29.xxx token)
        creds.refresh(Request())

        print(f"[VertexSA] 🔑 Token refreshed for {os.path.basename(abs_path)}: "
              f"...{creds.token[-6:]} (expires {creds.expiry})")
        return creds.token

    except ImportError:
        print("[VertexSA] ❌ google-auth not installed. Run: pip install google-auth")
        return None
    except Exception as e:
        print(f"[VertexSA] ❌ Token refresh failed: {e}")
        return None


def get_random_sa_token(provider_config: dict) -> tuple:
    """
    Pick a random Service Account from provider's service_account_files list,
    get an access token, and return (token, project_id, sa_name).
    
    Args:
        provider_config: The provider dict from secrets.yaml containing service_account_files
        
    Returns:
        (token, project_id, sa_name) or (None, None, None) if failed
    """
    import random
    
    sa_files = provider_config.get("service_account_files", [])
    if not sa_files:
        # Fallback: single service_account_json path
        sa_json = provider_config.get("service_account_json", "")
        if sa_json:
            token = get_access_token(_resolve_path(sa_json))
            pid = get_project_id(_resolve_path(sa_json))
            return (token, pid, "default")
        return (None, None, None)
    
    # Shuffle and try each until one works
    candidates = list(sa_files)
    random.shuffle(candidates)
    
    for sa in candidates:
        json_path = _resolve_path(sa.get("json", ""))
        if not json_path or not os.path.exists(json_path):
            continue
        token = get_access_token(json_path)
        if token:
            project_id = sa.get("project_id") or get_project_id(json_path) or ""
            return (token, project_id, sa.get("name", ""))
    
    return (None, None, None)


def _resolve_path(path: str) -> str:
    """Resolve relative paths against the plugin directory."""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(plugin_dir, path)


def get_project_id(json_path: str) -> Optional[str]:
    """Extract project_id from a Service Account JSON file."""
    import json
    try:
        abs_path = _resolve_path(json_path)
        with open(abs_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("project_id")
    except Exception:
        return None
