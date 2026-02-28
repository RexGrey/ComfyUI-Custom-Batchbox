"""
Account core module for ComfyUI-Custom-Batchbox.

Account management singleton: authentication, credits, task status.
Ported from BlenderAIStudio src/studio/account/core.py
All bpy dependencies removed, config reads from yaml.
"""

import asyncio
import json
import logging
import traceback
import webbrowser
from copy import deepcopy
from pathlib import Path
from threading import Thread
from typing import Optional

import requests

from .network import get_session
from .task_history import AccountTaskHistory, TaskHistoryData
from .task_sync import TaskSyncService, TaskStatusPoller
from .websocket_server import WebSocketLoginServer
from .url_config import URLConfigManager
from .exceptions import (
    APIRequestException,
    AuthFailedException,
    ParameterValidationException,
    InsufficientBalanceException,
    RedeemCodeException,
    InternalException,
    DatabaseUpdateException,
    TokenExpiredException,
)

logger = logging.getLogger("batchbox.account")

# Auth modes
AUTH_MODE_API = "api"
AUTH_MODE_ACCOUNT = "account"


class Account:
    """Account management class (singleton).

    Responsibilities:
    - User authentication (login, logout)
    - Credit management (query, redeem)
    - Price table management
    - Task status queries (network layer)
    - Error queue management
    """

    _INSTANCE = None

    def __new__(cls, *args, **kwargs):
        if cls._INSTANCE is None:
            cls._INSTANCE = super().__new__(cls)
        return cls._INSTANCE

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return

        # User info
        self.nickname = ""
        self.logged_in = False
        self.services_connected = False
        self.credits = 0
        self._token = ""

        # Price table
        self.price_table = []
        self.provider_count_map = {}
        self._pricing_data = {}  # {model_name: {strategy: {modelId, prices...}}}

        # Task history and sync
        self.task_history = AccountTaskHistory()
        self.sync_service = TaskSyncService(self, self.task_history)
        self.task_poller = TaskStatusPoller(self, self.sync_service, interval=15)

        # Credit redemption table
        self.redeem_to_credits_table = {
            6: 600,
            30: 3300,
            60: 7200,
            100: 13000,
        }

        # State flags
        self.initialized = False
        self.error_messages: list = []
        self.waiting_for_login = False
        self.token_expired = False

        # Config
        self._auth_mode = AUTH_MODE_ACCOUNT
        self._pricing_strategy = "bestPrice"

        # URL manager
        self._url_manager = URLConfigManager.get_instance()

        # Auth file path (in plugin directory)
        self._auth_path: Optional[Path] = None

        self._initialized = True

    # ==================== Configuration ====================

    def configure(self, plugin_dir: str, account_config: dict = None):
        """Configure account from yaml settings.

        Args:
            plugin_dir: Path to the plugin directory
            account_config: Account section from secrets.yaml
        """
        self._auth_path = Path(plugin_dir, ".auth.json")

        if account_config:
            self._auth_mode = account_config.get("auth_mode", AUTH_MODE_ACCOUNT)
            self._pricing_strategy = account_config.get(
                "pricing_strategy", "bestPrice"
            )
            self._url_manager.configure(account_config)

        # Load local account info
        self.load_account_info_from_local()

        # Check service connectivity
        self.ping_once()

        # Fetch credits and pricing data (needed for model ID resolution)
        self.fetch_credits()
        self.fetch_credits_price()

    # ==================== Properties ====================

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    @auth_mode.setter
    def auth_mode(self, mode: str):
        self._auth_mode = mode

    @property
    def pricing_strategy(self) -> str:
        return self._pricing_strategy

    @pricing_strategy.setter
    def pricing_strategy(self, strategy: str):
        self._pricing_strategy = strategy

    def resolve_model_id(self, model_display_name: str) -> str:
        """Resolve the Account-specific model ID from the pricing table.
        
        The Account service uses numeric IDs from pricing table, NOT Gemini model names.
        E.g. NanoBananaPro + bestPrice -> '2016805995212177411'
        
        Reads pricing_strategy dynamically from node_settings (api_config.yaml)
        so changes take effect immediately without restart.
        
        Args:
            model_display_name: Model display name like 'NanoBananaPro', 'NanoBanana2'
        
        Returns:
            Account model ID string, or empty string if not found
        """
        # Dynamically read pricing_strategy from node_settings
        try:
            from ..config_manager import config_manager
            node_settings = config_manager.get_node_settings()
            strategy = node_settings.get("pricing_strategy", self._pricing_strategy)
        except Exception:
            strategy = self._pricing_strategy
        
        model_data = self._pricing_data.get(model_display_name, {})
        strategy_data = model_data.get(strategy, {})
        model_id = strategy_data.get("modelId", "")
        
        strategy_label = "低价优先" if strategy == "bestPrice" else "稳定优先"
        if model_id:
            logger.info(f"[Account] Resolved model ID: {model_display_name} + {strategy} ({strategy_label}) -> {model_id}")
        else:
            logger.warning(f"[Account] Cannot resolve model ID for {model_display_name} + {strategy}, pricing_data keys: {list(self._pricing_data.keys())}")
        return str(model_id)

    def provider_count(self, model_name: str) -> int:
        for price_data in self.price_table:
            if price_data.get("modelName") == model_name:
                return price_data.get("providerCount", 0)
        return 0

    @property
    def help_url(self) -> str:
        return self._url_manager.get_help_url()

    @property
    def service_url(self) -> str:
        return self._url_manager.get_service_url()

    @property
    def login_url(self) -> str:
        return self._url_manager.get_login_url()

    @property
    def token(self) -> str:
        dev_token = self._url_manager.get_dev_token()
        if dev_token:
            return dev_token
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value

    # ==================== Singleton ====================

    @classmethod
    def get_instance(cls) -> "Account":
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    def init(self):
        if self.initialized:
            return
        self.init_force()

    def init_force(self):
        logger.debug("Initializing account")
        self.initialized = True
        self.ping_once()
        self.fetch_credits()
        self.fetch_credits_price()

    # ==================== Error management ====================

    def take_errors(self) -> list:
        errors = self.error_messages[:]
        self.error_messages.clear()
        return errors

    def push_error(self, error):
        self.error_messages.append(error)

    # ==================== Login status ====================

    def is_logged_in(self) -> bool:
        return self.logged_in

    def is_waiting_for_login(self) -> bool:
        return self.waiting_for_login

    def get_status(self) -> dict:
        """Get current account status as dict (for REST API)."""
        return {
            "logged_in": self.logged_in,
            "waiting_for_login": self.waiting_for_login,
            "nickname": self.nickname,
            "credits": self.credits,
            "auth_mode": self._auth_mode,
            "services_connected": self.services_connected,
            "token_expired": self.token_expired,
            "errors": [str(e) for e in self.take_errors()],
        }

    # ==================== Login / Logout ====================

    def login(self):
        if self.waiting_for_login:
            return {"success": False, "error": "已在等待登录中"}

        self.waiting_for_login = True
        webbrowser.open(self.login_url)
        logger.info(f"Opening login URL: {self.login_url}")

        async def login_callback(
            server: WebSocketLoginServer, websocket, event: dict
        ):
            try:
                data: dict = event.get("data", {})
                self.load_account_info(data)
                self.save_account_info(data)
                self.init_force()
                response = {
                    "type": "send_token_return",
                    "data": {
                        "status": "ok",
                        "host": "ComfyUI",
                    },
                }
                await websocket.send(json.dumps(response))
                server.stop_event.set()
            except Exception:
                traceback.print_exc()

        def run(port_range):
            server = None
            for p in range(*port_range):
                try:
                    logger.info(f"Trying WebSocket server on port {p}...")
                    server = WebSocketLoginServer(p)
                    server.reg_handler("send_token", login_callback)
                    server.run()  # Blocks until login completes or fails
                    logger.info(f"WebSocket server on port {p} finished")
                    break
                except OSError:
                    logger.debug(f"Port {p} is in use, trying next")
                except Exception:
                    traceback.print_exc()

            if not server:
                logger.critical("No available port found for WebSocket login server")
            self.waiting_for_login = False

        job = Thread(target=run, args=((55441, 55451),), daemon=True)
        job.start()

        return {"success": True, "status": "login_started"}

    def logout(self):
        self.logged_in = False
        self.nickname = "Not Login"
        self.credits = 0
        self._token = ""
        if self._auth_path and self._auth_path.exists():
            try:
                self._auth_path.unlink()
            except Exception:
                pass
        return {"status": "logged_out"}

    # ==================== Account info load/save ====================

    def load_account_info_from_local(self):
        if not self._auth_path or not self._auth_path.exists():
            return
        try:
            data = json.loads(self._auth_path.read_text())
            self.load_account_info(data)
            self.fetch_credits()
        except Exception:
            traceback.print_exc()
            self.push_error("Can't load auth file")

    def load_account_info(self, data: dict):
        if not isinstance(data, dict):
            self.push_error("Invalid auth data")
            return
        self.nickname = data.get("nickname", "")
        self._token = data.get("token", "")
        self.credits = data.get("coin", 0)
        self.logged_in = True

    def save_account_info(self, data: dict):
        if not self._auth_path:
            return
        if not self._auth_path.parent.exists():
            try:
                self._auth_path.parent.mkdir(parents=True)
            except Exception:
                traceback.print_exc()
                self.push_error("Can't create auth directory")
        try:
            self._auth_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2)
            )
        except Exception:
            traceback.print_exc()
            self.push_error("Can't save auth file")

    # ==================== Service connectivity ====================

    def ping_once(self):
        url = f"{self.service_url}/billing/model-price"
        headers = {
            "Content-Type": "application/json",
        }

        def job():
            try:
                session = get_session()
                resp = session.get(url, headers=headers, timeout=2)
                self.services_connected = resp.status_code == 200
            except Exception:
                self.services_connected = False

        Thread(target=job, daemon=True).start()

    # ==================== Credit management ====================

    def redeem_credits(self, code: str) -> dict:
        url = f"{self.service_url}/billing/redeem-code"
        headers = {
            "X-Auth-T": self.token,
            "Content-Type": "application/json",
        }
        payload = {"code": code}

        try:
            session = get_session()
            resp = session.post(url, headers=headers, json=payload)
        except ConnectionError:
            return {"success": False, "error": "Network connection failed"}
        except Exception:
            traceback.print_exc()
            return {"success": False, "error": "Network connection failed"}

        if resp.status_code == 404:
            return {"success": False, "error": "Redeem failed"}
        if resp.status_code == 502:
            return {"success": False, "error": "Server Error: Bad Gateway"}

        try:
            resp.raise_for_status()
        except Exception as e:
            return {"success": False, "error": str(e)}

        if resp.status_code == 200:
            resp_json: dict = resp.json()
            code_val = resp_json.get("code")
            err_msg = resp_json.get("errMsg", "")

            if code_val != 0:
                return {"success": False, "error": err_msg or "Redeem failed"}

            data = resp_json.get("data", {"amount": 0})
            amount = data.get("amount", 0)
            self.credits = amount
            return {"success": True, "credits": amount}

        return {"success": False, "error": f"HTTP {resp.status_code}"}

    def fetch_credits(self):
        def _fetch_credits():
            if self._auth_mode != AUTH_MODE_ACCOUNT:
                return
            url = f"{self.service_url}/billing/balance"
            headers = {
                "X-Auth-T": self.token,
                "Content-Type": "application/json",
            }
            try:
                session = get_session()
                resp = session.get(url, headers=headers)
            except ConnectionError:
                self.push_error("Network connection failed")
                return
            except Exception:
                traceback.print_exc()
                self.push_error("Network connection failed")
                return

            if resp.status_code == 404:
                self.push_error("Credits fetch failed")
                return
            if resp.status_code == 502:
                self.push_error("Server Error: Bad Gateway")
                return

            try:
                resp.raise_for_status()
            except Exception:
                return

            if resp.status_code == 200:
                resp_json: dict = resp.json()
                code = resp_json.get("code")
                err_code = resp_json.get("errCode")
                err_msg = resp_json.get("errMsg", "")

                if code == -4 and err_code == -4000:
                    self.push_error(AuthFailedException("Authentication failed!"))
                elif code == -4 and err_code == -4001:
                    self.token_expired = True
                    self.push_error(TokenExpiredException("Token expired!"))
                    logger.warning("Token expired, user needs to re-login")

                if code != 0:
                    self.push_error("Credits fetch failed: " + err_msg)
                    return
                self.credits = resp_json.get("data", 0)
            else:
                self.push_error("Credits fetch failed: " + resp.text)

        Thread(target=_fetch_credits, daemon=True).start()

    # ==================== Price table management ====================

    def fetch_credits_price(self):
        def _fetch_credits_price():
            if self.price_table:
                logger.info("[Account] Price table already loaded, skipping fetch")
                return
            url = f"{self.service_url}/billing/model-price"
            logger.info(f"[Account] Fetching pricing data from: {url}")
            headers = {
                "Content-Type": "application/json",
            }
            try:
                session = get_session()
                resp = session.get(url, headers=headers)
            except ConnectionError:
                self.push_error("Network connection failed")
                logger.error("[Account] Price fetch: ConnectionError")
                return
            except Exception as e:
                traceback.print_exc()
                self.push_error("Network connection failed")
                logger.error(f"[Account] Price fetch exception: {e}")
                return

            logger.info(f"[Account] Price fetch response: HTTP {resp.status_code}")

            if resp.status_code == 404:
                self.push_error("Price fetch failed")
                return
            if resp.status_code == 502:
                self.push_error("Server Error: Bad Gateway")
                return

            try:
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"[Account] Price fetch HTTP error: {e}")
                return

            if resp.status_code == 200:
                resp_json: dict = resp.json()
                code = resp_json.get("code")
                err_msg = resp_json.get("errMsg")
                logger.info(f"[Account] Price API response: code={code}, errMsg={err_msg}")

                if code != 0:
                    self.push_error("Price fetch failed: " + str(err_msg))
                    return

                data = resp_json.get("data", {})
                logger.info(f"[Account] Price data type: {type(data).__name__}, len: {len(data) if hasattr(data, '__len__') else 'N/A'}")
                
                # Debug: log first item structure
                if isinstance(data, list) and len(data) > 0:
                    first_item = data[0]
                    logger.info(f"[Account] First item keys: {list(first_item.keys()) if isinstance(first_item, dict) else first_item}")
                
                self.price_table = deepcopy(data)
                pricing_data = {}

                for item in data if isinstance(data, list) else []:
                    model_name = item.get("modelName", None)
                    self.provider_count_map[model_name] = item.get(
                        "providerCount", 0
                    )
                    if model_name:
                        entry = deepcopy(item)
                        entry.pop("modelName", None)
                        entry.pop("providerCount", None)
                        pricing_data[model_name] = entry

                self._pricing_data = pricing_data
                logger.info(f"[Account] Pricing data loaded: {list(pricing_data.keys())}")
                
                # Debug: log resolved IDs for each model
                for name, model_data in pricing_data.items():
                    strategies = [k for k in model_data.keys() if isinstance(model_data[k], dict)]
                    logger.info(f"[Account]   {name}: strategies={strategies}")

            else:
                self.push_error("Price fetch failed: " + resp.text)

        Thread(target=_fetch_credits_price, daemon=True).start()

    # ==================== Task status queries ====================

    def add_task_ids_to_fetch_status_threaded(self, task_ids: list):
        self.task_poller.add_pending_task_ids(task_ids)

    def add_task_ids_to_fetch_status_now(self, task_ids: list):
        def _job(ids):
            self.sync_service.sync_tasks(ids)

        Thread(target=_job, args=(task_ids,), daemon=True).start()

    def _fetch_task_status(self, task_ids: list) -> dict:
        url = f"{self.service_url}/service/history"
        headers = {
            "X-Auth-T": self.token,
            "Content-Type": "application/json",
        }
        payload = {"reqIds": task_ids}

        try:
            session = get_session()
            resp = session.get(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch task status: {e}")
            raise

    def fetch_task_history(self, task_ids: list) -> dict:
        return self.task_history.fetch_task_history(task_ids)
