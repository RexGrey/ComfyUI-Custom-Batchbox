"""
ComfyUI-Custom-Batchbox Configuration Manager

Enhanced configuration manager supporting:
- Multiple API providers
- Dynamic parameter schemas
- Model-specific configurations
- Hot-reload capabilities
"""

import os
import time
import yaml
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CacheEntry:
    """Cache entry with TTL support"""
    data: Any
    created_at: float
    ttl: float = 300.0  # Default 5 minutes
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


@dataclass
class ProviderConfig:
    """API Provider configuration"""
    name: str
    display_name: str
    base_url: str
    api_key: str
    rate_limit: int = 60


@dataclass
class ParameterDef:
    """Parameter definition for dynamic UI"""
    name: str
    type: str  # string, select, boolean, number, slider
    label: str
    default: Any = None
    options: List[Dict] = None
    min: float = None
    max: float = None
    step: float = None
    multiline: bool = False
    required: bool = False
    depends_on: Dict = None


class ConfigManager:
    """
    Enhanced Configuration Manager with support for:
    - Multiple API providers
    - Dynamic parameter schemas per model
    - Hot-reload on file changes
    - TTL-based caching for performance
    """
    
    # Cache configuration
    CACHE_TTL = 300.0  # 5 minutes default TTL
    FILE_CHECK_INTERVAL = 5.0  # Check file every 5 seconds max
    
    def __init__(self):
        self._config: Dict = {}
        self._last_mtime: float = 0
        self._last_file_check: float = 0
        self._secrets_mtime: float = 0  # Track secrets file modification time
        
        # TTL-based caches
        self._providers_cache: Dict[str, CacheEntry] = {}
        self._models_cache: Dict[str, CacheEntry] = {}
        self._schema_cache: Dict[str, CacheEntry] = {}
        
        self.config_path = os.path.join(os.path.dirname(__file__), "api_config.yaml")
        self.secrets_path = os.path.join(os.path.dirname(__file__), "secrets.yaml")
        self.load_config()

    def load_config(self, force: bool = False) -> bool:
        """
        Loads or reloads the configuration if file changed.
        Uses throttled file checking to reduce I/O overhead.
        Also loads and merges secrets from secrets.yaml if available.
        
        Args:
            force: If True, bypass the file check interval throttle
        """
        if not os.path.exists(self.config_path):
            print(f"[ConfigManager] Config file not found at {self.config_path}")
            return False
        
        # Throttle file stat checks to reduce I/O
        current_time = time.time()
        if not force and (current_time - self._last_file_check) < self.FILE_CHECK_INTERVAL:
            return False
        
        self._last_file_check = current_time
        config_reloaded = False

        try:
            # Check main config file
            mtime = os.path.getmtime(self.config_path)
            secrets_mtime = os.path.getmtime(self.secrets_path) if os.path.exists(self.secrets_path) else 0
            
            # Reload if either file changed
            if mtime > self._last_mtime or secrets_mtime > self._secrets_mtime:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
                self._last_mtime = mtime
                
                # Merge secrets if available
                self._merge_secrets()
                self._secrets_mtime = secrets_mtime
                
                self._invalidate_caches()
                print(f"[ConfigManager] Loaded configuration from {self.config_path}")
                config_reloaded = True
        except Exception as e:
            print(f"[ConfigManager] Error loading config: {e}")
            return False
        return config_reloaded
    
    def _merge_secrets(self):
        """
        Merge providers from secrets.yaml into the main config.
        The entire providers section is stored in secrets.yaml to keep
        sensitive data (API keys, base URLs) together and out of version control.
        """
        if not os.path.exists(self.secrets_path):
            print(f"[ConfigManager] Warning: secrets.yaml not found at {self.secrets_path}")
            print(f"[ConfigManager] Please copy secrets.yaml.example to secrets.yaml and add your providers")
            return
        
        try:
            with open(self.secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f) or {}
            
            # Merge entire providers section from secrets.yaml
            if "providers" in secrets:
                self._config["providers"] = secrets["providers"]
            
            print(f"[ConfigManager] Merged providers from {self.secrets_path}")
        except Exception as e:
            print(f"[ConfigManager] Error loading secrets: {e}")

    def _invalidate_caches(self):
        """Clear all cached data after config reload"""
        self._providers_cache.clear()
        self._models_cache.clear()
        self._schema_cache.clear()
    
    # ==========================================
    # Config Validation
    # ==========================================
    
    def validate_config(self, raise_on_error: bool = False) -> List[str]:
        """
        Validate the configuration file.
        
        Args:
            raise_on_error: If True, raise ValidationError on first error
            
        Returns:
            List of validation error messages (empty if valid)
        """
        from .errors import ConfigError, ValidationError
        import re
        
        errors = []
        
        # URL pattern for validation
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )
        
        # Validate providers
        providers = self._config.get("providers", {})
        if not providers:
            errors.append("No providers configured")
        
        for name, config in providers.items():
            # Required: base_url
            base_url = config.get("base_url", "")
            if not base_url:
                errors.append(f"Provider '{name}': missing 'base_url'")
            elif not url_pattern.match(base_url):
                errors.append(f"Provider '{name}': invalid URL format '{base_url}'")
        
        # Validate models
        models = self._config.get("models", {})
        for model_name, model_config in models.items():
            # Check api_endpoints
            endpoints = model_config.get("api_endpoints", [])
            if not endpoints:
                errors.append(f"Model '{model_name}': no api_endpoints configured")
                continue
            
            for idx, ep in enumerate(endpoints):
                provider_name = ep.get("provider", "")
                if not provider_name:
                    errors.append(f"Model '{model_name}' endpoint {idx}: missing 'provider'")
                elif provider_name not in providers:
                    errors.append(f"Model '{model_name}' endpoint {idx}: provider '{provider_name}' not found")
                
                # Check modes
                modes = ep.get("modes", {})
                if not modes:
                    errors.append(f"Model '{model_name}' endpoint {idx}: no modes configured")
                else:
                    for mode_name, mode_config in modes.items():
                        if not mode_config.get("endpoint"):
                            errors.append(f"Model '{model_name}' {mode_name}: missing 'endpoint' path")
        
        if raise_on_error and errors:
            raise ValidationError("Configuration validation failed", errors)
        
        return errors
    
    def is_valid(self) -> bool:
        """Check if current configuration is valid"""
        return len(self.validate_config()) == 0

    # ==========================================
    # Provider Methods
    # ==========================================
    
    def get_providers(self) -> List[str]:
        """Returns list of provider names"""
        self.load_config()
        return list(self._config.get("providers", {}).keys())
    
    def _get_cached(self, cache: Dict[str, CacheEntry], key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        if key in cache:
            entry = cache[key]
            if not entry.is_expired():
                return entry.data
            # Remove expired entry
            del cache[key]
        return None
    
    def _set_cached(self, cache: Dict[str, CacheEntry], key: str, data: Any):
        """Store value in cache with TTL"""
        cache[key] = CacheEntry(
            data=data,
            created_at=time.time(),
            ttl=self.CACHE_TTL
        )
    
    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """Get configuration for a specific provider with TTL caching"""
        self.load_config()
        
        # Check cache first
        cached = self._get_cached(self._providers_cache, provider_name)
        if cached is not None:
            return cached
        
        providers = self._config.get("providers", {})
        if provider_name not in providers:
            return None
        
        p = providers[provider_name]
        config = ProviderConfig(
            name=provider_name,
            display_name=p.get("display_name", provider_name),
            base_url=p.get("base_url", "").rstrip('/'),
            api_key=p.get("api_key", ""),
            rate_limit=p.get("rate_limit", 60)
        )
        self._set_cached(self._providers_cache, provider_name, config)
        return config

    # ==========================================
    # Category Methods
    # ==========================================
    
    def get_categories(self) -> Dict[str, Dict]:
        """Returns all node categories"""
        self.load_config()
        return self._config.get("node_categories", {})
    
    def get_enabled_categories(self) -> List[str]:
        """Returns list of enabled category names"""
        categories = self.get_categories()
        return [name for name, cfg in categories.items() if cfg.get("enabled", True)]

    # ==========================================
    # Model Methods
    # ==========================================
    
    def get_models(self, category: str = None) -> List[str]:
        """Returns list of model names, optionally filtered by category, in configured order"""
        self.load_config()
        models = self._config.get("models", {})
        
        if category:
            # Get models in category
            category_models = [name for name, cfg in models.items() 
                    if cfg.get("category") == category]
            # Sort by configured order
            return self._sort_models_by_order(category_models, category)
        return list(models.keys())
    
    def get_model_order(self, category: str) -> List[str]:
        """Get the configured order of models for a category"""
        self.load_config()
        model_order = self._config.get("model_order", {})
        return model_order.get(category, [])
    
    def set_model_order(self, category: str, order: List[str]) -> None:
        """Set the order of models for a category"""
        self.load_config()
        if "model_order" not in self._config:
            self._config["model_order"] = {}
        self._config["model_order"][category] = order
        self.save_config()
    
    def _sort_models_by_order(self, model_names: List[str], category: str) -> List[str]:
        """Sort model names according to configured order"""
        order = self.get_model_order(category)
        if not order:
            return model_names
        
        # Build order index map
        order_map = {name: i for i, name in enumerate(order)}
        max_index = len(order)
        
        # Sort: ordered models first by their index, then unordered models alphabetically
        return sorted(model_names, key=lambda x: (order_map.get(x, max_index), x))
    
    def get_model_config(self, model_name: str) -> Optional[Dict]:
        """Get full configuration for a specific model with TTL caching"""
        self.load_config()
        
        # Check cache first
        cached = self._get_cached(self._models_cache, model_name)
        if cached is not None:
            return cached
        
        models = self._config.get("models", {})
        if model_name not in models:
            return None
        
        config = models[model_name].copy()
        config['name'] = model_name
        self._set_cached(self._models_cache, model_name, config)
        return config
    
    def get_models_by_category(self, category: str) -> List[Dict]:
        """Get all models in a specific category, in configured order"""
        self.load_config()
        models = self._config.get("models", {})
        
        # Get models in category
        category_models = []
        for name, cfg in models.items():
            if cfg.get("category") == category:
                category_models.append({
                    "name": name,
                    "display_name": cfg.get("display_name", name),
                    "description": cfg.get("description", "")
                })
        
        # Sort by configured order
        order = self.get_model_order(category)
        if order:
            order_map = {name: i for i, name in enumerate(order)}
            max_index = len(order)
            category_models.sort(key=lambda x: (order_map.get(x["name"], max_index), x["name"]))
        
        return category_models

    # ==========================================
    # Parameter Schema Methods
    # ==========================================
    
    def get_parameter_schema(self, model_name: str) -> Optional[Dict]:
        """
        Get the parameter schema for a specific model with TTL caching.
        Used by frontend to dynamically render parameter controls.
        """
        self.load_config()
        
        # Check cache first
        cached = self._get_cached(self._schema_cache, model_name)
        if cached is not None:
            return cached
        
        model_config = self.get_model_config(model_name)
        if not model_config:
            return None
        
        schema = model_config.get("parameter_schema", {})
        self._set_cached(self._schema_cache, model_name, schema)
        return schema
    
    def get_parameter_schema_flat(self, model_name: str) -> List[Dict]:
        """
        Get flattened parameter schema as a list for easier iteration.
        Each item includes group info.
        """
        schema = self.get_parameter_schema(model_name)
        if not schema:
            return []
        
        result = []
        for group_name, params in schema.items():
            for param_name, param_def in params.items():
                item = {
                    "name": param_name,
                    "group": group_name,
                    **param_def
                }
                result.append(item)
        return result

    # ==========================================
    # API Endpoint Methods
    # ==========================================
    
    def get_api_endpoints(self, model_name: str) -> List[Dict]:
        """Get all API endpoints for a model, sorted by priority"""
        model_config = self.get_model_config(model_name)
        if not model_config:
            return []
        
        endpoints = model_config.get("api_endpoints", [])
        return sorted(endpoints, key=lambda x: x.get("priority", 999))
    
    def get_best_endpoint(self, model_name: str, mode: str = "text2img") -> Optional[Dict]:
        """
        Get the highest priority endpoint for a specific mode.
        Implements fallback: if requested mode not configured, use the other mode.
        """
        endpoints = self.get_api_endpoints(model_name)
        
        # Define fallback mode
        fallback_mode = "img2img" if mode == "text2img" else "text2img"
        
        for ep in endpoints:
            provider = self.get_provider_config(ep.get("provider"))
            if not provider or not provider.api_key:
                continue
            
            modes = ep.get("modes", {})
            
            # Try requested mode first
            if mode in modes and modes[mode].get("endpoint"):
                return {
                    "provider": provider,
                    "config": modes[mode],
                    "endpoint_config": ep
                }
            
            # Fallback to other mode if available
            if fallback_mode in modes and modes[fallback_mode].get("endpoint"):
                print(f"[ConfigManager] Mode '{mode}' not found, falling back to '{fallback_mode}'")
                return {
                    "provider": provider,
                    "config": modes[fallback_mode],
                    "endpoint_config": ep
                }
        
        return None
    
    def get_endpoint_by_name(self, model_name: str, endpoint_display_name: str, 
                              mode: str = "text2img") -> Optional[Dict]:
        """
        Get a specific endpoint by its display_name or provider name.
        Used for manual endpoint selection.
        """
        endpoints = self.get_api_endpoints(model_name)
        fallback_mode = "img2img" if mode == "text2img" else "text2img"
        
        for ep in endpoints:
            # Match by display_name or provider
            ep_name = ep.get("display_name") or ep.get("provider")
            if ep_name != endpoint_display_name:
                continue
            
            provider = self.get_provider_config(ep.get("provider"))
            if not provider or not provider.api_key:
                continue
            
            modes = ep.get("modes", {})
            
            # Try requested mode first
            if mode in modes and modes[mode].get("endpoint"):
                return {
                    "provider": provider,
                    "config": modes[mode],
                    "endpoint_config": ep
                }
            
            # Fallback to other mode if available
            if fallback_mode in modes and modes[fallback_mode].get("endpoint"):
                return {
                    "provider": provider,
                    "config": modes[fallback_mode],
                    "endpoint_config": ep
                }
        
        # If not found by name, fallback to priority-based
        print(f"[ConfigManager] Endpoint '{endpoint_display_name}' not found, using priority-based selection")
        return self.get_best_endpoint(model_name, mode)
    
    def get_endpoint_by_index(self, model_name: str, index: int, 
                               mode: str = "text2img") -> Optional[Dict]:
        """
        Get endpoint by index for round-robin selection.
        """
        endpoints = self.get_api_endpoints(model_name)
        if not endpoints:
            return None
        
        # Wrap around if index exceeds length
        actual_idx = index % len(endpoints)
        ep = endpoints[actual_idx]
        
        provider = self.get_provider_config(ep.get("provider"))
        if not provider or not provider.api_key:
            # Try next endpoint
            return self.get_best_endpoint(model_name, mode)
        
        modes = ep.get("modes", {})
        fallback_mode = "img2img" if mode == "text2img" else "text2img"
        
        # Try requested mode first
        if mode in modes and modes[mode].get("endpoint"):
            return {
                "provider": provider,
                "config": modes[mode],
                "endpoint_config": ep
            }
        
        # Fallback to other mode
        if fallback_mode in modes and modes[fallback_mode].get("endpoint"):
            return {
                "provider": provider,
                "config": modes[fallback_mode],
                "endpoint_config": ep
            }
        
        return self.get_best_endpoint(model_name, mode)
    
    def get_alternative_endpoints(self, model_name: str, mode: str = "text2img", 
                                   exclude_provider: str = None) -> List[Dict]:
        """Get alternative endpoints for failover"""
        endpoints = self.get_api_endpoints(model_name)
        result = []
        
        for ep in endpoints:
            if ep.get("provider") == exclude_provider:
                continue
            
            provider = self.get_provider_config(ep.get("provider"))
            if not provider or not provider.api_key:
                continue
            
            modes = ep.get("modes", {})
            if mode in modes:
                result.append({
                    "provider": provider,
                    "config": modes[mode],
                    "endpoint_config": ep
                })
        return result

    # ==========================================
    # Legacy Compatibility Methods
    # ==========================================
    
    def get_presets(self) -> List[str]:
        """Legacy method: Returns model names as presets"""
        return self.get_models()
    
    def get_preset_config(self, preset_name: str) -> Optional[Dict]:
        """
        Legacy method: Get preset config in old format.
        Maps new model config to old structure for backwards compatibility.
        """
        model_config = self.get_model_config(preset_name)
        if not model_config:
            return None
        
        # Get best endpoint
        endpoints = self.get_api_endpoints(preset_name)
        if not endpoints:
            return None
        
        first_ep = endpoints[0]
        provider = self.get_provider_config(first_ep.get("provider"))
        
        if not provider:
            return None
        
        # Build legacy format
        return {
            "provider": provider.name,
            "model_name": preset_name,
            "base_url": provider.base_url,
            "api_key": provider.api_key,
            "modes": first_ep.get("modes", {}),
            "polling": first_ep.get("polling", {})
        }
    
    def get_alternatives(self, original_preset_name: str) -> List[str]:
        """Legacy method: Get alternative presets (providers) for failover"""
        endpoints = self.get_api_endpoints(original_preset_name)
        if len(endpoints) <= 1:
            return []
        
        # Return provider names as alternatives
        return [ep.get("provider") for ep in endpoints[1:] 
                if self.get_provider_config(ep.get("provider"))]

    # ==========================================
    # Config Persistence Methods
    # ==========================================
    
    def get_raw_config(self) -> Dict:
        """Returns the raw config dictionary"""
        self.load_config()
        return self._config
    
    def save_config_data(self, new_config: Dict) -> bool:
        """
        Saves the configuration dictionary to api_config.yaml.
        Providers are excluded as they are stored in secrets.yaml.
        """
        try:
            # Create a deep copy to avoid modifying the original config
            import copy
            config_to_save = copy.deepcopy(new_config)
            
            # Remove entire providers section (stored in secrets.yaml)
            if "providers" in config_to_save:
                del config_to_save["providers"]
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_to_save, f, default_flow_style=False, 
                         allow_unicode=True, sort_keys=False)
            self._config = new_config  # Keep the full config with providers in memory
            self._last_mtime = os.path.getmtime(self.config_path)
            self._invalidate_caches()
            print(f"[ConfigManager] Configuration saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
            raise e
    
    def update_provider(self, provider_name: str, config: Dict) -> bool:
        """
        Update a specific provider's configuration.
        Separates sensitive data (api_key) to secrets.yaml and 
        non-sensitive data to api_config.yaml.
        """
        self.load_config()
        if "providers" not in self._config:
            self._config["providers"] = {}
        
        # Separate api_key from other config
        api_key = config.pop("api_key", None)
        
        # Save non-sensitive config to api_config.yaml
        self._config["providers"][provider_name] = config
        self.save_config_data(self._config)
        
        # Save api_key to secrets.yaml if provided
        if api_key is not None:
            self._save_provider_secret(provider_name, api_key)
        
        # Reload to merge secrets back into memory
        self.force_reload()
        return True
    
    def save_providers(self, providers: Dict) -> bool:
        """
        Save entire providers section to secrets.yaml.
        This keeps all provider info (including API keys) out of version control.
        """
        try:
            with open(self.secrets_path, 'w', encoding='utf-8') as f:
                # Add header comment
                f.write("# =============================================================================\n")
                f.write("# 🔐 供应商配置文件 (包含 API 密钥 - 请勿上传到 GitHub!)\n")
                f.write("# =============================================================================\n")
                f.write("# 此文件包含所有 API 供应商的配置信息\n")
                f.write("# 请复制 secrets.yaml.example 并重命名为 secrets.yaml\n")
                f.write("# =============================================================================\n\n")
                yaml.dump({"providers": providers}, f, default_flow_style=False, 
                         allow_unicode=True, sort_keys=False)
            
            print(f"[ConfigManager] Saved {len(providers)} providers to {self.secrets_path}")
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving providers: {e}")
            return False
    
    def update_model(self, model_name: str, config: Dict) -> bool:
        """Update a specific model's configuration"""
        self.load_config()
        if "models" not in self._config:
            self._config["models"] = {}
        
        self._config["models"][model_name] = config
        return self.save_config_data(self._config)

    # ==========================================
    # Hot Reload Methods
    # ==========================================
    
    def force_reload(self) -> bool:
        """
        Force reload the configuration from disk, bypassing all caches.
        Returns True if configuration was reloaded.
        """
        self._last_file_check = 0  # Reset check interval
        self._last_mtime = 0  # Force reload on next check
        return self.load_config(force=True)
    
    def config_changed_since(self, timestamp: float) -> bool:
        """
        Check if configuration file has been modified since the given timestamp.
        Useful for clients to check if they need to refresh.
        """
        if not os.path.exists(self.config_path):
            return False
        try:
            mtime = os.path.getmtime(self.config_path)
            return mtime > timestamp
        except Exception:
            return False
    
    def get_config_mtime(self) -> float:
        """
        Get the last modification time of the config file.
        Returns 0 if file doesn't exist or can't be read.
        """
        if not os.path.exists(self.config_path):
            return 0
        try:
            return os.path.getmtime(self.config_path)
        except Exception:
            return 0

    # ==========================================
    # Settings Methods
    # ==========================================
    
    def get_settings(self) -> Dict:
        """Get global settings with defaults"""
        self.load_config()
        defaults = {
            "default_timeout": 600,
            "max_retries": 3,
            "retry_delay": 1.0,
            "retry_on": [429, 502, 503, 504],
            "auto_failover": True,
            "log_level": "INFO"
        }
        settings = self._config.get("settings", {})
        # Merge with defaults
        for key, value in defaults.items():
            if key not in settings:
                settings[key] = value
        return settings
    
    def get_retry_config(self) -> Dict:
        """Get retry-specific configuration for adapters"""
        settings = self.get_settings()
        return {
            "max_retries": settings.get("max_retries", 3),
            "initial_delay": settings.get("retry_delay", 1.0),
            "retryable_codes": settings.get("retry_on", [429, 502, 503, 504])
        }
    
    def get_log_level(self) -> str:
        """Get configured log level"""
        settings = self.get_settings()
        return settings.get("log_level", "INFO").upper()
    
    def get_save_settings(self) -> Dict:
        """Get save settings with defaults for auto-save feature"""
        self.load_config()
        defaults = {
            "enabled": True,
            "output_dir": "batchbox",
            "format": "png",
            "quality": 95,
            "naming_pattern": "{model}_{timestamp}_{seed}",
            "create_date_subfolder": True,
            "include_prompt": False,
            "prompt_max_length": 50,
        }
        save_settings = self._config.get("save_settings", {})
        # Merge with defaults
        for key, value in defaults.items():
            if key not in save_settings:
                save_settings[key] = value
        return save_settings
    
    def update_save_settings(self, new_settings: Dict) -> bool:
        """Update save settings in config file"""
        self.load_config()
        if "save_settings" not in self._config:
            self._config["save_settings"] = {}
        self._config["save_settings"].update(new_settings)
        return self.save_config_data(self._config)
    
    def get_node_settings(self) -> Dict:
        """Get node settings with defaults (e.g., default_width)"""
        self.load_config()
        defaults = {
            "default_width": 500,  # Default node width in pixels
            "bypass_queue_prompt": True,  # Whether to exclude BatchBox nodes from global Queue Prompt
            "smart_cache_hash_check": True,  # Whether to check param hash for cache invalidation
        }
        node_settings = self._config.get("node_settings", {})
        # Merge with defaults
        for key, value in defaults.items():
            if key not in node_settings:
                node_settings[key] = value
        return node_settings
    
    def update_node_settings(self, new_settings: Dict) -> bool:
        """Update node settings in config file"""
        self.load_config()
        if "node_settings" not in self._config:
            self._config["node_settings"] = {}
        self._config["node_settings"].update(new_settings)
        return self.save_config_data(self._config)


# Global instance
config_manager = ConfigManager()

# Initialize logger from config
try:
    from .batchbox_logger import configure_logging
    configure_logging(level=config_manager.get_log_level())
except ImportError:
    pass  # Logger not yet imported

