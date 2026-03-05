"""
URL configuration manager for Account system.

Manages all service URLs with support for dev/production environments.
Ported from BlenderAIStudio src/studio/config/url_config.py
"""

import logging

logger = logging.getLogger("batchbox.account")


class URLConfigManager:
    """URL configuration manager (singleton).

    Responsibilities:
    - Manage all service URLs
    - Support production/dev environment switching
    - Read config from yaml settings
    - Provide URL construction methods
    """

    # Production configuration
    PRODUCTION_CONFIG = {
        "help_url": "https://shimo.im/docs/47kgMZ7nj4Sm963V",
        "api_base_url": "https://api-addon.acggit.com",
        "api_version": "v1",
        "login_url": "https://addon-login.acggit.com",
    }

    _instance = None

    def __init__(self):
        self._dev_mode = False
        self._dev_api_base_url = ""
        self._dev_login_url = ""
        self._dev_token = ""

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def configure(self, account_config: dict):
        """Configure from yaml settings.

        Args:
            account_config: dict from secrets.yaml account section
        """
        if not account_config:
            return
        self._dev_mode = account_config.get("use_dev_environment", False)
        self._dev_api_base_url = account_config.get("dev_api_base_url", "")
        self._dev_login_url = account_config.get("dev_login_url", "")
        self._dev_token = account_config.get("dev_token", "")

        # Allow overriding production URLs
        if account_config.get("api_base_url"):
            self.PRODUCTION_CONFIG["api_base_url"] = account_config["api_base_url"]
        if account_config.get("login_url"):
            self.PRODUCTION_CONFIG["login_url"] = account_config["login_url"]

    def is_dev_environment(self) -> bool:
        return self._dev_mode

    def get_help_url(self) -> str:
        return self.PRODUCTION_CONFIG["help_url"]

    def get_service_base_url(self) -> str:
        if self._dev_mode and self._dev_api_base_url:
            return self._dev_api_base_url.strip().rstrip("/")
        return self.PRODUCTION_CONFIG["api_base_url"]

    def get_service_url(self) -> str:
        base = self.get_service_base_url()
        version = self.PRODUCTION_CONFIG["api_version"]
        return f"{base}/{version}"

    def get_login_url(self) -> str:
        if self._dev_mode and self._dev_login_url:
            return self._dev_login_url.strip()
        return self.PRODUCTION_CONFIG["login_url"]

    def get_dev_token(self) -> str:
        if self._dev_mode and self._dev_token:
            return self._dev_token.strip()
        return ""

    def get_model_api_base_url(self, auth_mode: str):
        if auth_mode == "account":
            return self.get_service_url()
        return None
