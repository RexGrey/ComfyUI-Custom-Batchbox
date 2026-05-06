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
import re
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit
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


_SENSITIVE_QUERY_KEYS = {
    "key",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "access_token",
    "id_token",
    "refresh_token",
    "token",
    "auth",
    "authorization",
    "signature",
    "x-amz-signature",
    "x-goog-signature",
}

_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:key|api[_-]?key|apikey|access[_-]?key|secret[_-]?key|"
    r"access[_-]?token|id[_-]?token|refresh[_-]?token|token|auth|authorization|"
    r"signature|x-amz-signature|x-goog-signature)=)([^&\s\)\]\}\"']+)"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|secret[_-]?key|"
    r"access[_-]?token|id[_-]?token|refresh[_-]?token|token|authorization)"
    r"\s*[:=]\s*)([^&\s,;\)\]\}\"']+)"
)
_BEARER_SECRET_RE = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+")


def _is_sensitive_query_key(name: str) -> bool:
    return str(name or "").lower() in _SENSITIVE_QUERY_KEYS


def sanitize_url(url: Any) -> Any:
    """Mask sensitive query parameters in URLs before logging or returning text."""
    if url is None:
        return None

    text = str(url)
    try:
        parsed = urlsplit(text)
        if not parsed.query:
            return sanitize_text(text)

        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        changed = False
        safe_pairs = []
        for key, value in pairs:
            if _is_sensitive_query_key(key):
                safe_pairs.append((key, "***"))
                changed = True
            else:
                safe_pairs.append((key, value))

        if not changed:
            return sanitize_text(text)

        safe_query = "&".join(
            f"{quote_plus(str(key))}={quote_plus(str(value), safe='*')}"
            for key, value in safe_pairs
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))
    except Exception:
        return sanitize_text(text)


def sanitize_text(value: Any) -> Any:
    """Mask common secret shapes in free-form log/error text."""
    if value is None:
        return None

    text = str(value)
    text = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}***", text)
    text = _ASSIGNMENT_SECRET_RE.sub(lambda m: f"{m.group(1)}***", text)
    text = _BEARER_SECRET_RE.sub(lambda m: f"{m.group(1)}***", text)
    return text


def _sanitize_headers(headers: dict) -> dict:
    safe_headers = {}
    for key, value in (headers or {}).items():
        lower_key = str(key).lower()
        if any(token in lower_key for token in ("authorization", "api-key", "x-api-key", "x-auth", "token")):
            prefix = "Bearer" if str(value).lower().startswith("bearer ") else ""
            safe_headers[key] = f"{prefix} ***...".strip()
        else:
            safe_headers[key] = sanitize_text(value)
    return safe_headers


def _sanitize_log_arg(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_log_arg(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_sanitize_log_arg(item) for item in value)
    if isinstance(value, list):
        return [_sanitize_log_arg(item) for item in value]
    return value


class SecretRedactionFilter(logging.Filter):
    """Last-line defense: redact secrets from all batchbox log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize_text(record.msg)
            if isinstance(record.args, dict):
                record.args = {key: _sanitize_log_arg(value) for key, value in record.args.items()}
            elif record.args:
                record.args = tuple(_sanitize_log_arg(value) for value in record.args)
        except Exception:
            pass
        return True


def _install_secret_redaction_filter():
    for handler in logger.handlers:
        if not any(isinstance(flt, SecretRedactionFilter) for flt in handler.filters):
            handler.addFilter(SecretRedactionFilter())
    if not any(isinstance(flt, SecretRedactionFilter) for flt in logger.filters):
        logger.addFilter(SecretRedactionFilter())


_install_secret_redaction_filter()


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
    url = sanitize_url(url)
    logger.info(f"➡️ {method} {url}")
    
    if logger.isEnabledFor(logging.DEBUG):
        safe_headers = _sanitize_headers(headers)
        
        logger.debug(f"   Headers: {safe_headers}")
        
        if payload:
            # Truncate large payloads
            payload_str = sanitize_text(payload)
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
        response_text = sanitize_text(response_text)
        # Truncate large responses
        if len(response_text) > 500:
            response_text = response_text[:500] + "..."
        logger.debug(f"   Response: {response_text}")


def log_error(message: str, exception: Exception = None):
    """Log an error"""
    safe_message = sanitize_text(message)
    if exception:
        logger.error(f"[ERROR] {safe_message}: {type(exception).__name__} - {sanitize_text(exception)}")
    else:
        logger.error(f"[ERROR] {safe_message}")
