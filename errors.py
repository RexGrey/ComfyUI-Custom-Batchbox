"""
Batchbox Error Classes

Provides structured error handling with detailed context for:
- Configuration errors
- API request/response errors
- Validation errors
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any


class BatchboxError(Exception):
    """Base exception for all Batchbox errors"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict:
        """Convert error to dictionary for API responses"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


class ConfigError(BatchboxError):
    """Configuration-related errors"""
    
    def __init__(self, message: str, field: Optional[str] = None, 
                 value: Any = None, suggestion: Optional[str] = None):
        self.field = field
        self.value = value
        self.suggestion = suggestion
        
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["value"] = str(value)[:100]  # Truncate for safety
        if suggestion:
            details["suggestion"] = suggestion
        
        super().__init__(message, details)
    
    def __str__(self):
        parts = [self.message]
        if self.field:
            parts.append(f"Field: {self.field}")
        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")
        return " | ".join(parts)


class ValidationError(BatchboxError):
    """Validation errors with multiple issues"""
    
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        self.errors = errors or []
        details = {"errors": self.errors} if self.errors else {}
        super().__init__(message, details)
    
    def __str__(self):
        if self.errors:
            return f"{self.message}: {', '.join(self.errors)}"
        return self.message


@dataclass
class APIError(BatchboxError):
    """
    API request/response errors with full context.
    
    Attributes:
        message: Human-readable error description
        provider: API provider name
        status_code: HTTP status code (0 if not HTTP error)
        response_body: Raw response body (truncated)
        retryable: Whether this error is likely transient
        request_url: The URL that was called
        request_method: HTTP method used
    """
    message: str = ""
    provider: str = "unknown"
    status_code: int = 0
    response_body: str = ""
    retryable: bool = False
    request_url: str = ""
    request_method: str = ""
    
    def __post_init__(self):
        # Truncate response body
        if len(self.response_body) > 500:
            self.response_body = self.response_body[:500] + "..."
        
        # Set retryable based on status code if not explicitly set
        if self.status_code in [429, 502, 503, 504]:
            self.retryable = True
    
    def __str__(self):
        if self.status_code:
            return f"[{self.provider}] HTTP {self.status_code}: {self.message}"
        return f"[{self.provider}] {self.message}"
    
    def to_dict(self) -> Dict:
        return {
            "error": "APIError",
            "message": self.message,
            "provider": self.provider,
            "status_code": self.status_code,
            "retryable": self.retryable
        }


class TimeoutError(APIError):
    """Request timeout error"""
    
    def __init__(self, provider: str, timeout: float, url: str = ""):
        super().__init__(
            message=f"Request timed out after {timeout}s",
            provider=provider,
            status_code=0,
            retryable=True,
            request_url=url
        )
        self.timeout = timeout


class RateLimitError(APIError):
    """Rate limit exceeded error"""
    
    def __init__(self, provider: str, retry_after: Optional[int] = None):
        message = "Rate limit exceeded"
        if retry_after:
            message += f", retry after {retry_after}s"
        
        super().__init__(
            message=message,
            provider=provider,
            status_code=429,
            retryable=True
        )
        self.retry_after = retry_after


class AuthenticationError(APIError):
    """Authentication/authorization error"""
    
    def __init__(self, provider: str, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            provider=provider,
            status_code=401,
            retryable=False
        )


class ProviderError(APIError):
    """Provider-side error (5xx)"""
    
    def __init__(self, provider: str, status_code: int, message: str = ""):
        super().__init__(
            message=message or f"Provider error (HTTP {status_code})",
            provider=provider,
            status_code=status_code,
            retryable=status_code in [502, 503, 504]
        )


# Error factory for creating appropriate error types from HTTP responses
def create_api_error(
    provider: str,
    status_code: int,
    response_body: str = "",
    url: str = ""
) -> APIError:
    """
    Factory function to create appropriate APIError subclass based on status code.
    """
    if status_code == 401 or status_code == 403:
        return AuthenticationError(provider, f"HTTP {status_code}: Unauthorized")
    
    if status_code == 429:
        return RateLimitError(provider)
    
    if status_code >= 500:
        return ProviderError(provider, status_code, response_body[:200])
    
    # Generic API error for other cases
    return APIError(
        message=response_body[:200] if response_body else f"HTTP {status_code}",
        provider=provider,
        status_code=status_code,
        response_body=response_body,
        request_url=url
    )
