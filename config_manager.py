import os
import yaml

class ConfigManager:
    def __init__(self):
        self._config = {}
        self._last_mtime = 0
        self.config_path = os.path.join(os.path.dirname(__file__), "api_config.yaml")
        self.load_config()

    def load_config(self):
        """Loads or reloads the configuration if file changed."""
        if not os.path.exists(self.config_path):
            print(f"[ConfigManager] Config file not found at {self.config_path}")
            return

        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime > self._last_mtime:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
                self._last_mtime = mtime
                print(f"[ConfigManager] Loaded configuration from {self.config_path}")
        except Exception as e:
            print(f"[ConfigManager] Error loading config: {e}")

    def get_presets(self):
        """Returns a list of preset names."""
        self.load_config() # Auto-reload
        return list(self._config.get("presets", {}).keys())

    def get_preset_config(self, preset_name):
        """Returns the full configuration for a specific preset."""
        self.load_config()
        presets = self._config.get("presets", {})
        if preset_name not in presets:
            return None
        
        preset = presets[preset_name]
        provider_name = preset.get("provider")
        providers = self._config.get("providers", {})
        
        provider_config = providers.get(provider_name, {})
        
        # Merge provider config into preset config for convenience
        combined_config = preset.copy()
        combined_config["base_url"] = provider_config.get("base_url", "")
        combined_config["api_key"] = provider_config.get("api_key", "")
        
        return combined_config

    def save_config_data(self, new_config):
        """Saves the configuration dictionary to the file."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            self._config = new_config
            # Update mtime to avoid immediate reload trigger
            self._last_mtime = os.path.getmtime(self.config_path) 
            print(f"[ConfigManager] Configuration saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
            raise e

    def get_raw_config(self):
        """Returns the raw config dictionary."""
        self.load_config()
        return self._config

    def get_alternatives(self, original_preset_name):
        """Finds other presets that share the same model_name (for load balancing)."""
        current_config = self.get_preset_config(original_preset_name)
        if not current_config:
            return []
        
        target_model = current_config.get("model_name")
        alternatives = []
        
        presets = self._config.get("presets", {})
        for name, data in presets.items():
            if name != original_preset_name and data.get("model_name") == target_model:
                 alternatives.append(name)
        
        return alternatives

# Global instance
config_manager = ConfigManager()
