"""
Tests for Generic API Adapter
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests
import yaml
from pathlib import Path

# Import from parent directory
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.generic import GenericAPIAdapter
from adapters.base import APIResponse
from batchbox_logger import RetryConfig


class TestGenericAPIAdapter:
    """Test GenericAPIAdapter class"""
    
    @pytest.fixture
    def provider_config(self):
        return {
            "name": "test_provider",
            "base_url": "https://api.test.com",
            "api_key": "test-api-key-123"
        }
    
    @pytest.fixture
    def endpoint_config(self):
        return {
            "provider": "test_provider",
            "model_name": "test-model",
            "priority": 1,
            "modes": {
                "text2img": {
                    "endpoint": "/v1/images/generate",
                    "method": "POST",
                    "content_type": "application/json"
                }
            }
        }
    
    @pytest.fixture
    def mode_config(self):
        return {
            "endpoint": "/v1/images/generate",
            "method": "POST",
            "content_type": "application/json",
            "response_type": "sync",
            "response_path": "data[0].url"
        }
    
    @pytest.fixture
    def adapter(self, provider_config, endpoint_config, mode_config):
        return GenericAPIAdapter(provider_config, endpoint_config, mode_config)
    
    def test_init(self, adapter, provider_config):
        """Test adapter initialization"""
        assert adapter.base_url == "https://api.test.com"
        assert adapter.api_key == "test-api-key-123"
    
    def test_build_request_json(self, adapter):
        """Test building JSON request"""
        params = {"prompt": "a cat", "size": "1024x1024"}
        request = adapter.build_request(params, "text2img")
        
        assert request["url"] == "https://api.test.com/v1/images/generate"
        assert request["method"] == "POST"
        assert "Authorization" in request["headers"]
        assert "json" in request or "data" in request
    
    def test_build_request_includes_model(self, adapter):
        """Test that model name is auto-added to payload"""
        params = {"prompt": "test"}
        request = adapter.build_request(params, "text2img")
        
        # Model should be in the json payload
        if "json" in request:
            assert request["json"].get("model") == "test-model"

    def test_build_request_excludes_configured_params(self, provider_config, endpoint_config):
        """Test that endpoint configs can prevent unsupported params from being sent."""
        mode_config = {
            "endpoint": "/v1/images/generate",
            "method": "POST",
            "content_type": "application/json",
            "exclude_params": ["seed"],
        }
        adapter = GenericAPIAdapter(provider_config, endpoint_config, mode_config)

        request = adapter.build_request(
            {"prompt": "test", "seed": 123, "size": "1024x1024"},
            "text2img",
        )

        assert "seed" not in request["json"]
        assert request["json"]["size"] == "1024x1024"

    def test_build_request_excludes_endpoint_level_params(self, provider_config, endpoint_config):
        """Test that provider endpoints can exclude unsupported params for every mode."""
        endpoint_config = {
            **endpoint_config,
            "exclude_params": ["resolution", "background"],
        }
        mode_config = {
            "endpoint": "/v1/images/generate",
            "method": "POST",
            "content_type": "application/json",
        }
        adapter = GenericAPIAdapter(provider_config, endpoint_config, mode_config)

        request = adapter.build_request(
            {
                "prompt": "test",
                "resolution": "2k",
                "background": "opaque",
                "quality": "high",
            },
            "text2img",
        )

        assert "resolution" not in request["json"]
        assert "background" not in request["json"]
        assert request["json"]["quality"] == "high"

    @patch.object(GenericAPIAdapter, "_download_image", return_value=b"fake-image")
    @patch('requests.request')
    def test_execute_success(self, mock_request, _mock_download, adapter):
        """Test successful API execution"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"url": "https://example.com/image.png"}]
        }
        mock_response.text = '{"data": [{"url": "https://example.com/image.png"}]}'
        mock_request.return_value = mock_response
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is True
        assert len(result.image_urls) > 0
    
    @patch('requests.request')
    def test_execute_http_error(self, mock_request, adapter):
        """Test handling of HTTP errors"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_request.return_value = mock_response
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is False
        assert "500" in result.error_message
    
    @patch('requests.request')
    def test_execute_timeout(self, mock_request, adapter):
        """Test handling of request timeout"""
        mock_request.side_effect = requests.Timeout()
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is False
        assert "timeout" in result.error_message.lower()

    @patch('requests.request')
    def test_execute_connection_error_redacts_api_key_from_error(self, mock_request):
        """Connection errors returned to nodes must not expose query API keys."""
        secret = "AIzaSyFakeSecretForRegression"
        adapter = GenericAPIAdapter(
            {
                "name": "google_official",
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key": secret,
            },
            {
                "provider": "google_official",
                "api_format": "gemini",
                "auth_header_format": "none",
                "model_name": "demo-model",
            },
            {
                "endpoint": "/models/{{model}}:generateContent?key={api_key}",
                "method": "POST",
                "content_type": "application/json",
            },
        )
        mock_request.side_effect = requests.ConnectionError(
            f"Failed to establish connection for /models/demo-model:generateContent?key={secret}&alt=json"
        )

        result = adapter.execute(
            {"prompt": "test"},
            "text2img",
            retry_config=RetryConfig(max_retries=0),
        )

        assert result.success is False
        assert secret not in result.error_message
        assert "key=***" in result.error_message


class TestFileFormatHandling:
    """Test multipart file format handling"""
    
    @pytest.fixture
    def img2img_adapter(self):
        provider = {
            "name": "test",
            "base_url": "https://api.test.com",
            "api_key": "key"
        }
        endpoint = {"provider": "test"}
        mode = {
            "endpoint": "/v1/edit",
            "method": "POST",
            "content_type": "multipart/form-data",
            "file_format": "indexed",
            "file_field": "images"
        }
        return GenericAPIAdapter(provider, endpoint, mode)
    
    def test_file_format_from_config(self, img2img_adapter):
        """Test that file format config is respected"""
        # This would need actual image data to fully test
        # For now, just verify config is accessible
        assert img2img_adapter.mode_config.get("file_format") == "indexed"
        assert img2img_adapter.mode_config.get("file_field") == "images"


class TestResponseParsing:
    """Test response parsing"""
    
    @pytest.fixture
    def adapter(self):
        provider = {"name": "test", "base_url": "https://api.test.com", "api_key": "key"}
        endpoint = {}
        mode = {
            "response_type": "sync",
            "response_path": "data[*].url"
        }
        return GenericAPIAdapter(provider, endpoint, mode)
    
    def test_parse_single_image_url(self, adapter):
        """Test parsing single image URL"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"url": "https://example.com/img1.png"}]
        }
        
        result = adapter.parse_response(mock_response)
        
        assert result.success is True
        assert "https://example.com/img1.png" in result.image_urls
    
    def test_parse_multiple_image_urls(self, adapter):
        """Test parsing multiple image URLs"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {"url": "https://example.com/img1.png"},
                {"url": "https://example.com/img2.png"}
            ]
        }
        
        result = adapter.parse_response(mock_response)
        
        assert result.success is True
        assert len(result.image_urls) >= 1  # At least one parsed

    @patch.object(GenericAPIAdapter, "_download_image", return_value=b"fake-image")
    @patch("adapters.generic.time.sleep")
    @patch("adapters.generic.requests.get")
    @patch("adapters.generic.requests.request")
    def test_execute_async_apimart_polling(
        self,
        mock_request,
        mock_get,
        mock_sleep,
        _mock_download,
    ):
        """Test APIMart-style async image generation and task polling."""
        provider = {
            "name": "apimart",
            "base_url": "https://api.apimart.ai",
            "api_key": "test-key",
        }
        endpoint = {
            "provider": "apimart",
            "model_name": "gpt-image-2-official",
        }
        mode = {
            "endpoint": "/v1/images/generations",
            "method": "POST",
            "content_type": "application/json",
            "response_type": "async",
            "task_id_path": "data.0.task_id",
            "polling_endpoint": "/v1/tasks/{{task_id}}",
            "poll_interval": 5,
            "status_path": "data.status",
            "success_value": "completed",
            "response_path": "data.result.images[*].url[0]",
            "exclude_params": ["seed"],
            "payload_template": {
                "model": "gpt-image-2-official",
                "prompt": "{{prompt}}",
                "size": "{{size}}",
                "resolution": "{{resolution}}",
                "quality": "{{quality}}",
                "background": "{{background}}",
                "moderation": "{{moderation}}",
                "output_format": "{{output_format}}",
                "n": "{{n}}",
            },
        }
        adapter = GenericAPIAdapter(provider, endpoint, mode)

        submit_response = Mock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "code": 200,
            "data": [{"status": "submitted", "task_id": "task_123"}],
        }
        submit_response.text = '{"code": 200}'
        mock_request.return_value = submit_response

        poll_response = Mock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "code": 200,
            "data": {
                "id": "task_123",
                "status": "completed",
                "result": {
                    "images": [
                        {"url": ["https://example.com/result.png"]}
                    ]
                },
            },
        }
        mock_get.return_value = poll_response

        result = adapter.execute(
            {
                "prompt": "星空下的古老城堡",
                "size": "16:9",
                "resolution": "2k",
                "quality": "high",
                "background": "auto",
                "moderation": "auto",
                "output_format": "png",
                "n": 1,
                "seed": 123,
            },
            "text2img",
            retry_config=RetryConfig(max_retries=0),
        )

        assert result.success is True
        assert result.image_urls == ["https://example.com/result.png"]
        assert result.images == [b"fake-image"]
        assert mock_request.call_args.args[:2] == (
            "POST",
            "https://api.apimart.ai/v1/images/generations",
        )
        assert mock_request.call_args.kwargs["json"] == {
            "model": "gpt-image-2-official",
            "prompt": "星空下的古老城堡",
            "size": "16:9",
            "resolution": "2k",
            "quality": "high",
            "background": "auto",
            "moderation": "auto",
            "output_format": "png",
            "n": 1,
        }
        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == "https://api.apimart.ai/v1/tasks/task_123"
        mock_sleep.assert_called_once_with(5.0)

def test_gpt_image_2_apimart_official_schema_and_endpoint_config():
    """GPT-Image-2 exposes APIMart official params without leaking them to legacy endpoints."""
    project_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((project_root / "api_config.yaml").read_text(encoding="utf-8"))
    model = config["models"]["gpt_image_2"]
    assert model["show_seed_widget"] is False
    basic = model["parameter_schema"]["basic"]
    advanced = model["parameter_schema"]["advanced"]

    assert basic["resolution"]["default"] == "1k"
    assert [opt["value"] for opt in basic["resolution"]["options"]] == ["1k", "2k", "4k"]
    assert basic["size"]["default"] == "auto"
    assert [opt["value"] for opt in basic["size"]["options"]] == [
        "auto",
        "1:1",
        "3:2",
        "2:3",
        "4:3",
        "3:4",
        "5:4",
        "4:5",
        "16:9",
        "9:16",
        "2:1",
        "1:2",
        "21:9",
        "9:21",
    ]
    assert basic["quality"]["default"] == "auto"
    assert [opt["value"] for opt in basic["quality"]["options"]] == [
        "auto",
        "low",
        "medium",
        "high",
    ]
    assert basic["output_format"]["default"] == "png"
    assert basic["n"]["default"] == 1
    assert basic["n"]["min"] == 1
    assert basic["n"]["max"] == 4

    assert advanced["background"]["default"] == "auto"
    assert advanced["moderation"]["default"] == "auto"
    assert advanced["output_compression"]["default"] == ""
    assert advanced["mask_url"]["default"] == ""

    apimart = next(ep for ep in model["api_endpoints"] if ep["provider"] == "apimart")
    apimart_fields = {
        "resolution",
        "background",
        "moderation",
        "output_format",
        "output_compression",
        "n",
        "mask_url",
    }
    for mode_config in apimart["modes"].values():
        assert mode_config["response_type"] == "async"
        assert mode_config["task_id_path"] == "data.0.task_id"
        assert mode_config["polling_endpoint"] == "/v1/tasks/{{task_id}}"
        assert mode_config["payload_template"] == {
            "model": "gpt-image-2-official",
            "prompt": "{{prompt}}",
            "size": "{{size}}",
            "resolution": "{{resolution}}",
            "quality": "{{quality}}",
            "background": "{{background}}",
            "moderation": "{{moderation}}",
            "output_format": "{{output_format}}",
            "n": "{{n}}",
        }
        assert "seed" in mode_config["exclude_params"]

    legacy_excluded = apimart_fields | {"size", "quality"}
    for ep in model["api_endpoints"]:
        if ep["provider"] == "apimart":
            continue
        assert legacy_excluded.issubset(set(ep["exclude_params"]))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
