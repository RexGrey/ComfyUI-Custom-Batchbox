"""
Tests for adapters/volcengine.py

Covers: Signature V4 (HMAC-SHA256), build_request, parse_response.
"""

import os
import base64
import importlib
from unittest.mock import Mock, patch

import pytest

# volcengine.py uses `from ..batchbox_logger import ...` (hard relative import).
# We must import it under the correct package path so Python resolves `..`.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pkg = os.path.basename(_project_root)
_volc_mod = importlib.import_module(f"{_pkg}.adapters.volcengine")
VolcengineAdapter = _volc_mod.VolcengineAdapter
APIResponse = importlib.import_module(f"{_pkg}.adapters.base").APIResponse


def _make_adapter(req_key="jimeng_t2i_anything", **overrides):
    provider = {
        "base_url": "https://visual.volcengineapi.com",
        "access_key": "AKTEST123",
        "secret_key": "SKTEST456",
        **overrides.pop("provider", {}),
    }
    endpoint = {
        "req_key": req_key,
        **overrides.pop("endpoint", {}),
    }
    mode = overrides.pop("mode", {})
    return VolcengineAdapter(provider, endpoint, mode)


# ──────────────────────────────────────────────────────────────────────────────
# Signature V4
# ──────────────────────────────────────────────────────────────────────────────

class TestSignatureV4:

    def test_sign_deterministic(self):
        a = _make_adapter()
        result1 = a._sign(b"key", "msg")
        result2 = a._sign(b"key", "msg")
        assert result1 == result2
        assert isinstance(result1, bytes)
        assert len(result1) == 32  # SHA-256 digest length

    def test_get_signature_key_derivation(self):
        a = _make_adapter()
        key = a._get_signature_key("secret", "20260101", "cn-north-1", "cv")
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_build_auth_headers_contains_required_fields(self):
        a = _make_adapter()
        headers = {"Content-Type": "application/json", "Host": "visual.volcengineapi.com"}
        result = a._build_auth_headers("POST", "/", "Action=Test", "{}", headers)
        assert "Authorization" in result
        assert "X-Date" in result
        assert "X-Content-Sha256" in result

    def test_authorization_format(self):
        a = _make_adapter()
        headers = {"Content-Type": "application/json", "Host": "visual.volcengineapi.com"}
        result = a._build_auth_headers("POST", "/", "Action=Test", "{}", headers)
        auth = result["Authorization"]
        assert auth.startswith("HMAC-SHA256 Credential=AKTEST123/")
        assert "SignedHeaders=" in auth
        assert "Signature=" in auth


# ──────────────────────────────────────────────────────────────────────────────
# build_request
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildRequest:

    def test_t2i_request(self):
        a = _make_adapter(req_key="jimeng_t2i_anything")
        req = a.build_request({"prompt": "a cat", "seed": 42}, mode="text2img")
        assert "url" in req
        assert "CVSync2AsyncSubmitTask" in req["url"]
        body = req["json"]
        assert body["req_key"] == "jimeng_t2i_anything"
        assert body["prompt"] == "a cat"
        assert body["seed"] == 42

    def test_i2i_with_images(self):
        a = _make_adapter(req_key="i2i_inpainting")
        img_bytes = b"fake_image_data"
        params = {
            "prompt": "edit",
            "_upload_files": [("image1", ("image1.png", img_bytes, "image/png"))],
        }
        req = a.build_request(params, mode="inpaint")
        body = req["json"]
        assert "binary_data_base64" in body
        assert len(body["binary_data_base64"]) == 1
        decoded = base64.b64decode(body["binary_data_base64"][0])
        assert decoded == img_bytes

    def test_i2i_no_images_error(self):
        a = _make_adapter(req_key="i2i_inpainting")
        req = a.build_request({}, mode="inpaint")
        assert "_error" in req

    def test_missing_req_key_raises(self):
        a = _make_adapter(req_key="")
        with pytest.raises(ValueError, match="req_key"):
            a.build_request({"prompt": "test"})


# ──────────────────────────────────────────────────────────────────────────────
# parse_response
# ──────────────────────────────────────────────────────────────────────────────

class TestParseResponse:

    def test_success_with_task_id(self):
        resp = Mock()
        resp.json.return_value = {
            "code": 10000,
            "data": {"task_id": "task-abc-123"},
        }
        a = _make_adapter()
        result = a.parse_response(resp)
        assert result.success is True
        assert result.task_id == "task-abc-123"
        assert result.status == "pending"

    def test_error_response(self):
        resp = Mock()
        resp.json.return_value = {
            "code": 40001,
            "message": "Invalid parameter",
        }
        a = _make_adapter()
        result = a.parse_response(resp)
        assert result.success is False
        assert "40001" in result.error_message

    def test_invalid_json(self):
        resp = Mock()
        resp.json.side_effect = ValueError("bad json")
        resp.text = "not json"
        a = _make_adapter()
        result = a.parse_response(resp)
        assert result.success is False
        assert "Invalid JSON" in result.error_message

    def test_direct_binary_result(self):
        img_b64 = base64.b64encode(b"direct_image").decode()
        resp = Mock()
        resp.json.return_value = {
            "code": 10000,
            "data": {"binary_data_base64": [img_b64]},
        }
        a = _make_adapter()
        result = a.parse_response(resp)
        assert result.success is True
        assert result.images[0] == b"direct_image"

    def test_no_task_id_no_images(self):
        resp = Mock()
        resp.json.return_value = {"code": 10000, "data": {}}
        a = _make_adapter()
        result = a.parse_response(resp)
        assert result.success is False
        assert "No task_id" in result.error_message


class TestExecution:

    def test_poll_and_download_fetches_missing_image_bytes(self):
        adapter = _make_adapter()
        with patch.object(
            adapter,
            "_poll_for_result",
            return_value=APIResponse(
                success=True,
                image_urls=["https://example.com/1.png", "https://example.com/2.png"],
            ),
        ):
            with patch.object(
                adapter,
                "_download_image",
                side_effect=[b"img-1", b"img-2"],
            ) as mock_download:
                result = adapter.poll_and_download("task-1")

        assert result.success is True
        assert result.images == [b"img-1", b"img-2"]
        assert mock_download.call_count == 2

    def test_execute_polls_pending_task_ids(self):
        adapter = _make_adapter()
        pending = APIResponse(success=True, task_id="task-1", status="pending")
        completed = APIResponse(success=True, images=[b"final"])

        with patch.object(adapter, "submit_task", return_value=pending) as mock_submit:
            with patch.object(
                adapter,
                "poll_and_download",
                return_value=completed,
            ) as mock_poll:
                result = adapter.execute({"prompt": "cat"}, mode="text2img")

        assert result.images == [b"final"]
        mock_submit.assert_called_once_with({"prompt": "cat"}, "text2img")
        mock_poll.assert_called_once_with("task-1")

    def test_execute_downloads_direct_result_urls_without_polling(self):
        adapter = _make_adapter()
        direct = APIResponse(
            success=True,
            image_urls=["https://example.com/direct.png"],
            status="success",
        )

        with patch.object(adapter, "submit_task", return_value=direct):
            with patch.object(
                adapter,
                "_download_image",
                return_value=b"direct-bytes",
            ) as mock_download:
                with patch.object(adapter, "poll_and_download") as mock_poll:
                    result = adapter.execute({"prompt": "cat"}, mode="text2img")

        assert result.images == [b"direct-bytes"]
        mock_download.assert_called_once_with("https://example.com/direct.png")
        mock_poll.assert_not_called()
