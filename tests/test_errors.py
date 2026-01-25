"""
Tests for Batchbox Error Classes
"""

import pytest
from errors import (
    BatchboxError, ConfigError, ValidationError,
    APIError, TimeoutError, RateLimitError, 
    AuthenticationError, ProviderError, create_api_error
)


class TestBatchboxError:
    """Test base error class"""
    
    def test_basic_error(self):
        err = BatchboxError("Something went wrong")
        assert err.message == "Something went wrong"
        assert err.details == {}
        assert str(err) == "Something went wrong"
    
    def test_error_with_details(self):
        err = BatchboxError("Error", {"key": "value"})
        assert err.details == {"key": "value"}
    
    def test_to_dict(self):
        err = BatchboxError("Test error", {"foo": "bar"})
        d = err.to_dict()
        assert d["error"] == "BatchboxError"
        assert d["message"] == "Test error"
        assert d["details"]["foo"] == "bar"


class TestConfigError:
    """Test configuration errors"""
    
    def test_basic_config_error(self):
        err = ConfigError("Invalid config")
        assert str(err) == "Invalid config"
    
    def test_config_error_with_field(self):
        err = ConfigError("Missing required field", field="api_key")
        assert err.field == "api_key"
        assert "api_key" in str(err)
    
    def test_config_error_with_suggestion(self):
        err = ConfigError(
            "Invalid URL", 
            field="base_url", 
            value="not-a-url",
            suggestion="Use format: https://api.example.com"
        )
        assert "Suggestion" in str(err)
        assert err.suggestion == "Use format: https://api.example.com"


class TestValidationError:
    """Test validation errors with multiple issues"""
    
    def test_single_error(self):
        err = ValidationError("Validation failed", ["Missing api_key"])
        assert len(err.errors) == 1
    
    def test_multiple_errors(self):
        errors = [
            "Missing api_key",
            "Invalid base_url",
            "No endpoints configured"
        ]
        err = ValidationError("Validation failed", errors)
        assert len(err.errors) == 3
        assert "Missing api_key" in str(err)


class TestAPIError:
    """Test API error class"""
    
    def test_basic_api_error(self):
        err = APIError(
            message="Request failed",
            provider="openai",
            status_code=500
        )
        assert err.provider == "openai"
        assert err.status_code == 500
        assert "[openai]" in str(err)
    
    def test_retryable_status_codes(self):
        for code in [429, 502, 503, 504]:
            err = APIError(message="Error", provider="test", status_code=code)
            assert err.retryable is True
    
    def test_non_retryable_codes(self):
        err = APIError(message="Error", provider="test", status_code=400)
        assert err.retryable is False
    
    def test_response_body_truncation(self):
        long_body = "x" * 1000
        err = APIError(message="Error", provider="test", response_body=long_body)
        assert len(err.response_body) < 600  # 500 + "..."


class TestSpecializedErrors:
    """Test specialized error subclasses"""
    
    def test_timeout_error(self):
        err = TimeoutError(provider="openai", timeout=30.0)
        assert "30" in str(err)
        assert err.retryable is True
    
    def test_rate_limit_error(self):
        err = RateLimitError(provider="openai", retry_after=60)
        assert err.status_code == 429
        assert err.retry_after == 60
        assert "60" in err.message
    
    def test_authentication_error(self):
        err = AuthenticationError(provider="openai")
        assert err.status_code == 401
        assert err.retryable is False
    
    def test_provider_error(self):
        err = ProviderError(provider="openai", status_code=503)
        assert err.status_code == 503
        assert err.retryable is True


class TestCreateAPIError:
    """Test error factory function"""
    
    def test_creates_auth_error_for_401(self):
        err = create_api_error("openai", 401, "Unauthorized")
        assert isinstance(err, AuthenticationError)
    
    def test_creates_rate_limit_for_429(self):
        err = create_api_error("openai", 429, "Too many requests")
        assert isinstance(err, RateLimitError)
    
    def test_creates_provider_error_for_5xx(self):
        err = create_api_error("openai", 503, "Service unavailable")
        assert isinstance(err, ProviderError)
    
    def test_creates_generic_for_4xx(self):
        err = create_api_error("openai", 400, "Bad request")
        assert type(err) == APIError


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
