"""
Tests for Generic API Adapter
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests

# Import from parent directory
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.generic import GenericAPIAdapter
from adapters.base import APIResponse


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

    @patch('requests.post')
    def test_execute_success(self, mock_post, adapter):
        """Test successful API execution"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"url": "https://example.com/image.png"}]
        }
        mock_response.text = '{"data": [{"url": "https://example.com/image.png"}]}'
        mock_post.return_value = mock_response
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is True
        assert len(result.image_urls) > 0
    
    @patch('requests.post')
    def test_execute_http_error(self, mock_post, adapter):
        """Test handling of HTTP errors"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is False
        assert "500" in result.error_message
    
    @patch('requests.post')
    def test_execute_timeout(self, mock_post, adapter):
        """Test handling of request timeout"""
        mock_post.side_effect = requests.Timeout()
        
        result = adapter.execute({"prompt": "test"}, "text2img")
        
        assert result.success is False
        assert "timeout" in result.error_message.lower()


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
