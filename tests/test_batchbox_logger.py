"""
Tests for batchbox_logger.py

Covers: RequestTimer, RetryConfig, calculate_delay, should_retry,
        retry_request decorator, log_request, log_response, log_error.
"""

import time
import logging
from unittest.mock import Mock, patch

import pytest
import requests

from batchbox_logger import (
    RequestTimer,
    RetryConfig,
    RETRYABLE_STATUS_CODES,
    DEFAULT_RETRY_CONFIG,
    should_retry,
    calculate_delay,
    retry_request,
    log_request,
    log_response,
    log_error,
    configure_logging,
    logger,
)


# ──────────────────────────────────────────────────────────────────────────────
# RequestTimer
# ──────────────────────────────────────────────────────────────────────────────

class TestRequestTimer:

    def test_tracks_elapsed(self):
        with RequestTimer("op") as t:
            time.sleep(0.02)
        assert t.elapsed >= 0.01

    def test_returns_self(self):
        with RequestTimer("op") as t:
            pass
        assert isinstance(t, RequestTimer)

    def test_start_time_set(self):
        with RequestTimer("op") as t:
            assert t.start_time is not None

    def test_logs_debug(self, caplog):
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="batchbox"):
            with RequestTimer("test_op"):
                pass
        assert any("test_op" in r.message for r in caplog.records)
        logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────────────────────────────
# RetryConfig
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryConfig:

    def test_default_values(self):
        c = RetryConfig()
        assert c.max_retries == 3
        assert c.initial_delay == 1.0
        assert c.max_delay == 60.0
        assert c.exponential_base == 2.0
        assert c.retryable_codes == RETRYABLE_STATUS_CODES

    def test_custom_values(self):
        c = RetryConfig(max_retries=5, initial_delay=0.5, max_delay=30.0,
                        exponential_base=3.0, retryable_codes=[500])
        assert c.max_retries == 5
        assert c.initial_delay == 0.5
        assert c.retryable_codes == [500]

    def test_default_retryable_codes(self):
        assert RETRYABLE_STATUS_CODES == [429, 502, 503, 504]

    def test_default_config_instance(self):
        assert isinstance(DEFAULT_RETRY_CONFIG, RetryConfig)


# ──────────────────────────────────────────────────────────────────────────────
# calculate_delay
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateDelay:

    def test_attempt_0(self):
        c = RetryConfig()
        assert calculate_delay(0, c) == 1.0

    def test_attempt_1(self):
        c = RetryConfig()
        assert calculate_delay(1, c) == 2.0

    def test_attempt_5(self):
        c = RetryConfig()
        assert calculate_delay(5, c) == 32.0

    def test_capped_at_max_delay(self):
        c = RetryConfig(max_delay=10.0)
        assert calculate_delay(5, c) == 10.0

    def test_custom_base_and_initial(self):
        c = RetryConfig(initial_delay=0.5, exponential_base=3.0)
        # 0.5 * 3^2 = 4.5
        assert calculate_delay(2, c) == 4.5


# ──────────────────────────────────────────────────────────────────────────────
# should_retry
# ──────────────────────────────────────────────────────────────────────────────

class TestShouldRetry:

    def test_retryable_status_code_429(self):
        resp = Mock(spec=requests.Response, status_code=429)
        assert should_retry(resp, DEFAULT_RETRY_CONFIG) is True

    def test_retryable_status_code_503(self):
        resp = Mock(spec=requests.Response, status_code=503)
        assert should_retry(resp, DEFAULT_RETRY_CONFIG) is True

    def test_non_retryable_status_code_400(self):
        resp = Mock(spec=requests.Response, status_code=400)
        assert should_retry(resp, DEFAULT_RETRY_CONFIG) is False

    def test_non_retryable_status_code_200(self):
        resp = Mock(spec=requests.Response, status_code=200)
        assert should_retry(resp, DEFAULT_RETRY_CONFIG) is False

    def test_timeout_exception(self):
        assert should_retry(requests.Timeout(), DEFAULT_RETRY_CONFIG) is True

    def test_connection_error(self):
        assert should_retry(requests.ConnectionError(), DEFAULT_RETRY_CONFIG) is True

    def test_other_exception(self):
        assert should_retry(ValueError("boom"), DEFAULT_RETRY_CONFIG) is False


# ──────────────────────────────────────────────────────────────────────────────
# retry_request decorator
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryRequestDecorator:

    @patch("batchbox_logger.time.sleep")
    def test_succeeds_first_try(self, mock_sleep):
        @retry_request()
        def fn():
            resp = Mock(spec=requests.Response, status_code=200)
            return resp

        result = fn()
        assert result.status_code == 200
        mock_sleep.assert_not_called()

    @patch("batchbox_logger.time.sleep")
    def test_retries_on_retryable_status(self, mock_sleep):
        call_count = 0

        @retry_request(config=RetryConfig(max_retries=3))
        def fn():
            nonlocal call_count
            call_count += 1
            code = 503 if call_count < 3 else 200
            return Mock(spec=requests.Response, status_code=code)

        result = fn()
        assert result.status_code == 200
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("batchbox_logger.time.sleep")
    def test_retries_on_timeout_then_succeeds(self, mock_sleep):
        call_count = 0

        @retry_request(config=RetryConfig(max_retries=2))
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.Timeout("timed out")
            return Mock(spec=requests.Response, status_code=200)

        result = fn()
        assert result.status_code == 200
        assert call_count == 2

    def test_raises_non_retryable_exception(self):
        @retry_request()
        def fn():
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            fn()


# ──────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestLogFunctions:

    def test_log_request_masks_auth_header(self, caplog):
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="batchbox"):
            log_request("POST", "https://api.test.com/v1",
                        headers={"Authorization": "Bearer sk-very-secret-long-key-1234567890"})
        # Auth header should be truncated
        assert any("..." in r.message for r in caplog.records if "Headers" in r.message)
        logger.setLevel(logging.INFO)

    def test_log_request_info_level(self, caplog):
        with caplog.at_level(logging.INFO, logger="batchbox"):
            log_request("GET", "https://api.test.com/models")
        assert any("GET" in r.message and "api.test.com" in r.message for r in caplog.records)

    def test_log_response_success(self, caplog):
        with caplog.at_level(logging.INFO, logger="batchbox"):
            log_response(200, 1.23, success=True)
        assert any("200" in r.message for r in caplog.records)

    def test_log_response_failure(self, caplog):
        with caplog.at_level(logging.INFO, logger="batchbox"):
            log_response(500, 0.5, success=False)
        assert any("500" in r.message for r in caplog.records)

    def test_log_error_with_exception(self, caplog):
        with caplog.at_level(logging.ERROR, logger="batchbox"):
            log_error("something broke", ValueError("bad value"))
        assert any("ValueError" in r.message and "bad value" in r.message for r in caplog.records)

    def test_log_error_without_exception(self, caplog):
        with caplog.at_level(logging.ERROR, logger="batchbox"):
            log_error("general failure")
        assert any("general failure" in r.message for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────────
# configure_logging
# ──────────────────────────────────────────────────────────────────────────────

class TestConfigureLogging:

    def test_set_debug_level(self):
        configure_logging("DEBUG")
        assert logger.level == logging.DEBUG
        configure_logging("INFO")  # restore

    def test_set_warning_level(self):
        configure_logging("WARNING")
        assert logger.level == logging.WARNING
        configure_logging("INFO")  # restore

    def test_include_timestamp(self):
        configure_logging("INFO", include_timestamp=True)
        fmt = logger.handlers[0].formatter._fmt
        assert "asctime" in fmt
        # restore
        configure_logging("INFO", include_timestamp=False)
