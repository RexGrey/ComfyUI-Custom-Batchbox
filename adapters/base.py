"""
Base API Adapter

Defines the abstract interface for all API adapters.
"""

import time
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from io import BytesIO


@dataclass
class APIResponse:
    """Standardized API response"""
    success: bool
    images: List[bytes] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)
    raw_response: Dict = field(default_factory=dict)
    error_message: str = ""
    task_id: str = ""
    status: str = ""  # pending, processing, success, failed


@dataclass
class APIError(Exception):
    """API Error with details"""
    message: str
    provider: str
    status_code: int = 0
    response_body: str = ""
    retryable: bool = False
    
    def __str__(self):
        return f"[{self.provider}] {self.message} (HTTP {self.status_code})"


class APIAdapter(ABC):
    """
    Abstract base class for API adapters.
    
    Each adapter implements the specific logic for:
    - Building requests for a specific provider/format
    - Parsing responses
    - Handling async polling if needed
    """
    
    def __init__(self, provider_config: Dict, endpoint_config: Dict):
        """
        Args:
            provider_config: Provider settings (base_url, api_key, etc.)
            endpoint_config: Endpoint settings (path, method, payload_template, etc.)
        """
        self.provider = provider_config
        self.endpoint = endpoint_config
        self.timeout = 600
        self.max_retries = 3
    
    @property
    def base_url(self) -> str:
        return self.provider.get("base_url", "").rstrip('/')
    # Class-level key blacklist: {key_suffix: expiry_timestamp}
    # Keys that returned 429/expired are skipped for 1 hour
    _bad_keys: Dict[str, float] = {}
    _BAD_KEY_TTL = 3600  # 1 hour
    
    @property
    def api_key(self) -> str:
        """Get API key with random selection, skipping blacklisted keys.
        
        Supports formats (in priority order):
          1. api_keys: [{name: "x", key: "...", enabled: true}, ...]  (named, filterable)
          2. api_keys: ["key1", "key2"]                               (plain list)
          3. api_key: "single_key"                                    (original)
        """
        import random
        import time
        
        keys_config = self.provider.get("api_keys", [])
        if keys_config and isinstance(keys_config, list):
            # Build list of active keys
            active_keys = []
            for item in keys_config:
                if isinstance(item, dict):
                    if item.get("enabled", True) and item.get("key"):
                        active_keys.append(item["key"])
                elif isinstance(item, str) and item:
                    active_keys.append(item)
            
            if active_keys:
                # Filter out blacklisted keys (always use CLASS-level dict, never instance)
                now = time.time()
                bad = APIAdapter._bad_keys  # explicit class reference
                good_keys = [k for k in active_keys if k not in bad or bad[k] < now]
                
                # Clean expired entries IN-PLACE (don't reassign to avoid shadowing)
                expired = [k for k, t in bad.items() if t < now]
                for k in expired:
                    del bad[k]
                
                # Use good keys if available, fall back to all keys if all blacklisted
                pool = good_keys if good_keys else active_keys
                key = random.choice(pool)
                # Key numbering: stable index based on config order (1-based)
                key_num = active_keys.index(key) + 1 if key in active_keys else "?"
                provider_name = self.provider.get("display_name", self.provider.get("name", "?"))
                skipped = len(active_keys) - len(good_keys)
                skip_info = f", {skipped} blacklisted" if skipped else ""
                print(f"[APIAdapter] 🔑 Key#{key_num} ...{key[-6:]} for {provider_name} ({len(pool)}/{len(active_keys)} keys{skip_info})")
                return key
        return self.provider.get("api_key", "")
    
    # Store active_keys list for key number lookup in blacklist_key
    _last_active_keys: list = []
    
    @classmethod
    def blacklist_key(cls, key: str, reason: str = ""):
        """Temporarily blacklist a key (e.g. quota exceeded, expired)."""
        import time
        cls._bad_keys[key] = time.time() + cls._BAD_KEY_TTL
        print(f"[APIAdapter] ⛔ Key ...{key[-6:]} blacklisted for 1h ({reason})")
    
    @abstractmethod
    def build_request(self, params: Dict, mode: str = "text2img") -> Dict:
        """
        Build the HTTP request from user parameters.
        
        Returns:
            Dict with keys: url, method, headers, body/data, files
        """
        pass
    
    @abstractmethod
    def parse_response(self, response: requests.Response) -> APIResponse:
        """
        Parse the HTTP response into standardized format.
        """
        pass
    
    @abstractmethod
    def execute(self, params: Dict, mode: str = "text2img") -> APIResponse:
        """
        Execute the full request cycle including retries and polling.
        """
        pass
    
    def get_headers(self, content_type: str = "application/json") -> Dict:
        """Build standard headers"""
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers
    
    def _download_image(self, url: str, retries: int = 3) -> Optional[bytes]:
        """Download image from URL with retry logic"""
        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=120)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                print(f"[APIAdapter] Download attempt {attempt + 1}/{retries} failed for {url}: {e}")
                if attempt < retries - 1:
                    import time
                    time.sleep(2 * (attempt + 1))  # Exponential backoff: 2s, 4s
        print(f"[APIAdapter] All {retries} download attempts failed for {url}")
        return None
    
    def _poll_for_result(self, task_id: str, timeout: int = 600) -> APIResponse:
        """
        Poll for async task completion.
        Override in subclasses for specific polling logic.
        """
        polling_config = self.endpoint.get("polling", {})
        poll_endpoint = polling_config.get("endpoint_template", "/v1/tasks/{task_id}")
        poll_url = f"{self.base_url}{poll_endpoint.format(task_id=task_id)}"
        
        status_path = self.endpoint.get("status_path", "status")
        success_value = self.endpoint.get("success_value", "SUCCESS")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(2)
            
            try:
                resp = requests.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30
                )
                
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                status = self._get_nested_value(data, status_path)
                
                if status == success_value:
                    return self.parse_response(resp)
                elif status in ["FAILURE", "FAILED", "ERROR"]:
                    return APIResponse(
                        success=False,
                        error_message=f"Task failed: {data}"
                    )
                    
            except Exception as e:
                print(f"[APIAdapter] Polling error: {e}")
        
        return APIResponse(
            success=False,
            error_message="Polling timeout"
        )
    
    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """Get value from nested dict using dot notation path"""
        keys = path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                return None
        
        return value
    
    def _set_nested_value(self, data: Dict, path: str, value: Any):
        """Set value in nested dict using dot notation path"""
        keys = path.split('.')
        current = data
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
