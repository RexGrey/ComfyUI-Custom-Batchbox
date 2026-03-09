"""
Tests for adapters/base.py

Covers: APIResponse dataclass, APIError dataclass,
        APIAdapter helper methods (get_headers, api_key, _get_nested_value,
        _set_nested_value, _download_image).
"""

from unittest.mock import patch, Mock

import pytest
import requests

from adapters.base import APIResponse, APIError, APIAdapter


# Concrete subclass for testing non-abstract methods
class _ConcreteAdapter(APIAdapter):
    def build_request(self, params, mode="text2img"):
        return {}

    def parse_response(self, response):
        return APIResponse(success=True)

    def execute(self, params, mode="text2img"):
        return APIResponse(success=True)


# ──────────────────────────────────────────────────────────────────────────────
# APIResponse
# ──────────────────────────────────────────────────────────────────────────────

class TestAPIResponse:

    def test_default_values(self):
        r = APIResponse(success=False)
        assert r.success is False
        assert r.images == []
        assert r.image_urls == []
        assert r.raw_response == {}
        assert r.error_message == ""
        assert r.task_id == ""
        assert r.status == ""

    def test_success_response(self):
        r = APIResponse(
            success=True,
            image_urls=["https://example.com/img.png"],
            status="success",
        )
        assert r.success is True
        assert len(r.image_urls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# APIError
# ──────────────────────────────────────────────────────────────────────────────

class TestBaseAPIError:

    def test_creation(self):
        e = APIError(message="fail", provider="test", status_code=500)
        assert str(e) == "[test] fail (HTTP 500)"

    def test_is_exception(self):
        assert issubclass(APIError, Exception)

    def test_retryable_default(self):
        e = APIError(message="x", provider="p")
        assert e.retryable is False


# ──────────────────────────────────────────────────────────────────────────────
# APIAdapter helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestAPIAdapterHelpers:

    def _make_adapter(self, provider_config=None, endpoint_config=None):
        p = provider_config or {"base_url": "https://api.test.com", "api_key": "sk-test"}
        e = endpoint_config or {}
        return _ConcreteAdapter(p, e)

    # get_headers
    def test_get_headers_default(self):
        a = self._make_adapter()
        h = a.get_headers()
        assert h["Authorization"] == "Bearer sk-test"
        assert h["Content-Type"] == "application/json"

    def test_get_headers_no_content_type(self):
        a = self._make_adapter()
        h = a.get_headers(content_type="")
        assert "Content-Type" not in h

    def test_get_headers_custom_content_type(self):
        a = self._make_adapter()
        h = a.get_headers(content_type="multipart/form-data")
        assert h["Content-Type"] == "multipart/form-data"

    # base_url
    def test_base_url_strips_trailing_slash(self):
        a = self._make_adapter({"base_url": "https://api.test.com/", "api_key": ""})
        assert a.base_url == "https://api.test.com"

    # api_key property
    def test_api_key_single(self):
        a = self._make_adapter({"base_url": "", "api_key": "sk-single"})
        assert a.api_key == "sk-single"

    @patch("random.choice", side_effect=lambda keys: keys[0])
    def test_api_key_plain_list(self, _):
        a = self._make_adapter({"base_url": "", "api_keys": ["k1", "k2", "k3"]})
        assert a.api_key == "k1"

    @patch("random.choice", side_effect=lambda keys: keys[0])
    def test_api_key_named_dicts(self, _):
        a = self._make_adapter({
            "base_url": "",
            "api_keys": [
                {"name": "main", "key": "sk-main", "enabled": True},
                {"name": "backup", "key": "sk-backup", "enabled": True},
            ]
        })
        assert a.api_key == "sk-main"

    @patch("random.choice", side_effect=lambda keys: keys[0])
    def test_api_key_disabled_filtered(self, _):
        a = self._make_adapter({
            "base_url": "",
            "api_keys": [
                {"name": "disabled", "key": "sk-no", "enabled": False},
                {"name": "active", "key": "sk-yes", "enabled": True},
            ]
        })
        assert a.api_key == "sk-yes"

    def test_api_key_empty_list_falls_back(self):
        a = self._make_adapter({"base_url": "", "api_keys": [], "api_key": "sk-fallback"})
        assert a.api_key == "sk-fallback"

    # _get_nested_value
    def test_get_nested_simple(self):
        a = self._make_adapter()
        data = {"a": {"b": {"c": 42}}}
        assert a._get_nested_value(data, "a.b.c") == 42

    def test_get_nested_list_index(self):
        a = self._make_adapter()
        data = {"data": [{"url": "http://img1"}, {"url": "http://img2"}]}
        assert a._get_nested_value(data, "data.0.url") == "http://img1"
        assert a._get_nested_value(data, "data.1.url") == "http://img2"

    def test_get_nested_missing_key(self):
        a = self._make_adapter()
        assert a._get_nested_value({"a": 1}, "b.c") is None

    # _set_nested_value
    def test_set_nested_creates_path(self):
        a = self._make_adapter()
        data = {}
        a._set_nested_value(data, "a.b.c", 99)
        assert data["a"]["b"]["c"] == 99

    def test_set_nested_existing_path(self):
        a = self._make_adapter()
        data = {"a": {"b": 1}}
        a._set_nested_value(data, "a.b", 2)
        assert data["a"]["b"] == 2

    # _download_image
    @patch("adapters.base.requests.get")
    def test_download_image_success(self, mock_get):
        mock_resp = Mock()
        mock_resp.content = b"fake-image-bytes"
        mock_resp.raise_for_status = Mock()
        mock_get.return_value = mock_resp

        a = self._make_adapter()
        result = a._download_image("https://example.com/img.png")
        assert result == b"fake-image-bytes"

    @patch("adapters.base.time.sleep")
    @patch("adapters.base.requests.get")
    def test_download_image_retries_then_succeeds(self, mock_get, mock_sleep):
        fail_resp = Mock()
        fail_resp.raise_for_status.side_effect = requests.HTTPError("503")

        ok_resp = Mock()
        ok_resp.content = b"ok"
        ok_resp.raise_for_status = Mock()

        mock_get.side_effect = [fail_resp, ok_resp]

        a = self._make_adapter()
        result = a._download_image("https://example.com/img.png", retries=2)
        assert result == b"ok"
        assert mock_get.call_count == 2

    @patch("adapters.base.time.sleep")
    @patch("adapters.base.requests.get")
    def test_download_image_all_retries_fail(self, mock_get, mock_sleep):
        fail_resp = Mock()
        fail_resp.raise_for_status.side_effect = requests.HTTPError("500")
        mock_get.return_value = fail_resp

        a = self._make_adapter()
        result = a._download_image("https://example.com/img.png", retries=2)
        assert result is None
        assert mock_get.call_count == 2
