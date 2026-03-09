"""
Tests for account/core.py

Covers: Account singleton, initial state, login/logout, status, error queue,
        load/save account info, resolve_model_id, provider_count.
"""

import importlib
import os
from unittest.mock import patch, MagicMock

import pytest

_pkg = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import account modules via package path
_core_mod = importlib.import_module(f"{_pkg}.account.core")
Account = _core_mod.Account


@pytest.fixture(autouse=True)
def reset_account_singleton():
    """Reset Account singleton between tests."""
    Account._INSTANCE = None
    yield
    Account._INSTANCE = None


@pytest.fixture
def account():
    """Create a fresh Account instance with mocked externals."""
    with patch.object(_core_mod, "get_session", return_value=MagicMock()), \
         patch.object(_core_mod.URLConfigManager, "get_instance", return_value=MagicMock()):
        acc = Account()
    return acc


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

class TestSingleton:

    def test_same_instance(self, account):
        acc2 = Account()
        assert acc2 is account

    def test_get_instance(self, account):
        assert Account.get_instance() is account


# ──────────────────────────────────────────────────────────────────────────────
# Initial State
# ──────────────────────────────────────────────────────────────────────────────

class TestInitialState:

    def test_not_logged_in(self, account):
        assert account.logged_in is False

    def test_zero_credits(self, account):
        assert account.credits == 0

    def test_empty_nickname(self, account):
        assert account.nickname == ""

    def test_empty_token(self, account):
        assert account._token == ""


# ──────────────────────────────────────────────────────────────────────────────
# Error Queue
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorQueue:

    def test_push_and_take(self, account):
        account.push_error("err1")
        account.push_error("err2")
        errors = account.take_errors()
        assert errors == ["err1", "err2"]

    def test_take_clears(self, account):
        account.push_error("x")
        account.take_errors()
        assert account.take_errors() == []


# ──────────────────────────────────────────────────────────────────────────────
# Load Account Info
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadAccountInfo:

    def test_load_sets_fields(self, account):
        account.load_account_info({
            "nickname": "TestUser",
            "token": "tok123",
            "coin": 500,
        })
        assert account.nickname == "TestUser"
        assert account._token == "tok123"
        assert account.credits == 500
        assert account.logged_in is True

    def test_load_invalid_pushes_error(self, account):
        account.load_account_info("not a dict")
        assert len(account.error_messages) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Logout
# ──────────────────────────────────────────────────────────────────────────────

class TestLogout:

    def test_logout_resets_state(self, account):
        account.logged_in = True
        account.nickname = "User"
        account.credits = 100
        account._token = "tok"
        result = account.logout()
        assert result == {"status": "logged_out"}
        assert account.logged_in is False
        assert account.credits == 0
        assert account._token == ""


# ──────────────────────────────────────────────────────────────────────────────
# Get Status
# ──────────────────────────────────────────────────────────────────────────────

class TestGetStatus:

    def test_status_dict_keys(self, account):
        status = account.get_status()
        assert "logged_in" in status
        assert "credits" in status
        assert "nickname" in status
        assert "errors" in status
        assert "auth_mode" in status


# ──────────────────────────────────────────────────────────────────────────────
# Resolve Model ID
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveModelId:

    def test_found(self, account):
        account._pricing_data = {
            "ModelA": {
                "bestPrice": {"modelId": "12345"},
            }
        }
        account._pricing_strategy = "bestPrice"
        # Patch config_manager in the module that resolve_model_id imports from
        import config_manager as cm_mod
        orig = cm_mod.config_manager.get_node_settings
        cm_mod.config_manager.get_node_settings = lambda: {"pricing_strategy": "bestPrice"}
        try:
            result = account.resolve_model_id("ModelA")
        finally:
            cm_mod.config_manager.get_node_settings = orig
        assert result == "12345"

    def test_not_found(self, account):
        account._pricing_data = {}
        result = account.resolve_model_id("NonExistent")
        assert result == ""


# ──────────────────────────────────────────────────────────────────────────────
# Provider Count
# ──────────────────────────────────────────────────────────────────────────────

class TestProviderCount:

    def test_found(self, account):
        account.price_table = [
            {"modelName": "M1", "providerCount": 3},
        ]
        assert account.provider_count("M1") == 3

    def test_not_found(self, account):
        account.price_table = []
        assert account.provider_count("Missing") == 0
