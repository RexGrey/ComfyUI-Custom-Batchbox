"""
Batchbox Logging and Retry Utilities

Provides:
- Configurable logging for all Batchbox components
- Request/response debugging
- Performance timing
- Retry with exponential backoff
"""

import time
import logging
import functools
from typing import Callable, List, Optional, Any

# ==========================================
# Logger Setup
# ==========================================

# Create logger
logger = logging.getLogger("batchbox")

# Default handler (console)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(name)s] %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def configure_logging(level: str = "INFO", include_timestamp: bool = False):
    """
    Configure the batchbox logger.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        include_timestamp: Whether to include timestamps in log messages
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    if include_timestamp:
        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        for handler in logger.handlers:
            handler.setFormatter(formatter)


# ==========================================
# Performance Timer
# ==========================================

class RequestTimer:
    """Context manager for timing API requests"""
    
    def __init__(self, operation: str):
        self.operation = operation
        self.start_time = None
        self.elapsed = 0
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, *args):
        self.elapsed = time.time() - self.start_time
        logger.debug(f"⏱️ {self.operation} took {self.elapsed:.2f}s")


# ==========================================
# Retry Decorator
# ==========================================

# Status codes that trigger retry
RETRYABLE_STATUS_CODES = [429, 502, 503, 504]


class RetryConfig:
    """Configuration for retry behavior"""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_codes: List[int] = None
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_codes = retryable_codes or RETRYABLE_STATUS_CODES


# Default retry config
DEFAULT_RETRY_CONFIG = RetryConfig()


def should_retry(response_or_exception: Any, config: RetryConfig) -> bool:
    """Determine if a request should be retried"""
    import requests
    
    if isinstance(response_or_exception, requests.Response):
        return response_or_exception.status_code in config.retryable_codes
    
    if isinstance(response_or_exception, (requests.Timeout, requests.ConnectionError)):
        return True
    
    return False


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for retry with exponential backoff"""
    delay = config.initial_delay * (config.exponential_base ** attempt)
    return min(delay, config.max_delay)


def retry_request(config: Optional[RetryConfig] = None):
    """
    Decorator for retrying requests with exponential backoff.
    
    Usage:
        @retry_request()
        def make_api_call():
            return requests.post(...)
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    
                    # Check if response indicates retryable error
                    import requests
                    if isinstance(result, requests.Response):
                        if result.status_code in config.retryable_codes:
                            if attempt < config.max_retries:
                                delay = calculate_delay(attempt, config)
                                logger.warning(
                                    f"🔄 Retry {attempt + 1}/{config.max_retries} "
                                    f"(HTTP {result.status_code}), waiting {delay:.1f}s"
                                )
                                time.sleep(delay)
                                continue
                    
                    return result
                    
                except Exception as e:
                    import requests
                    if isinstance(e, (requests.Timeout, requests.ConnectionError)):
                        last_exception = e
                        if attempt < config.max_retries:
                            delay = calculate_delay(attempt, config)
                            logger.warning(
                                f"🔄 Retry {attempt + 1}/{config.max_retries} "
                                f"({type(e).__name__}), waiting {delay:.1f}s"
                            )
                            time.sleep(delay)
                            continue
                    raise
            
            if last_exception:
                raise last_exception
            return result  # Return last result if all retries exhausted
        
        return wrapper
    return decorator


# ==========================================
# Request/Response Logging
# ==========================================

def log_request(method: str, url: str, headers: dict = None, 
                payload: dict = None, files: list = None):
    """Log an outgoing API request"""
    logger.info(f"➡️ {method} {url}")
    
    if logger.isEnabledFor(logging.DEBUG):
        # Mask API key in headers
        safe_headers = {}
        if headers:
            for k, v in headers.items():
                if "authorization" in k.lower():
                    safe_headers[k] = v[:20] + "..." if len(v) > 20 else v
                else:
                    safe_headers[k] = v
        
        logger.debug(f"   Headers: {safe_headers}")
        
        if payload:
            # Truncate large payloads
            payload_str = str(payload)
            if len(payload_str) > 500:
                payload_str = payload_str[:500] + "..."
            logger.debug(f"   Payload: {payload_str}")
        
        if files:
            logger.debug(f"   Files: {len(files)} file(s)")


def log_response(status_code: int, elapsed: float, 
                 response_text: str = None, success: bool = True):
    """Log an API response"""
    status_icon = "✅" if success else "❌"
    logger.info(f"⬅️ {status_icon} HTTP {status_code} ({elapsed:.2f}s)")
    
    if logger.isEnabledFor(logging.DEBUG) and response_text:
        # Truncate large responses
        if len(response_text) > 500:
            response_text = response_text[:500] + "..."
        logger.debug(f"   Response: {response_text}")


def log_error(message: str, exception: Exception = None):
    """Log an error"""
    if exception:
        logger.error(f"❌ {message}: {type(exception).__name__} - {str(exception)}")
    else:
        logger.error(f"❌ {message}")
