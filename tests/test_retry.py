"""
Tests for Retry Logic Utilities
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from googleapiclient.errors import HttpError
from http.client import HTTPResponse
import io

from src.utils.retry import (
    RetryConfig,
    is_retryable_http_error,
    is_rate_limit_error,
    is_server_error,
    is_retryable_error_code,
    retry_gmail_api,
    retry_calendar_api,
    retry_tasks_api,
    retry_generic_api,
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def create_http_error(status_code: int, reason: str = "Error") -> HttpError:
    """Create a mock HttpError for testing"""
    # Create a mock response
    resp = Mock()
    resp.status = status_code
    resp.reason = reason
    
    # Create HttpError
    content = f'{{"error": {{"code": {status_code}, "message": "{reason}"}}}}'.encode()
    return HttpError(resp=resp, content=content)


# ============================================
# TEST RETRY CONDITION FUNCTIONS
# ============================================

class TestRetryConditions:
    """Test retry condition functions"""
    
    def test_is_retryable_http_error_rate_limit(self):
        """Test rate limit error (429) is retryable"""
        error = create_http_error(429, "Rate Limit Exceeded")
        assert is_retryable_http_error(error) is True
    
    def test_is_retryable_http_error_server_errors(self):
        """Test server errors (5xx) are retryable"""
        for status_code in [500, 502, 503, 504]:
            error = create_http_error(status_code, "Server Error")
            assert is_retryable_http_error(error) is True
    
    def test_is_retryable_http_error_client_errors(self):
        """Test client errors (4xx except 429) are NOT retryable"""
        for status_code in [400, 401, 403, 404]:
            error = create_http_error(status_code, "Client Error")
            assert is_retryable_http_error(error) is False
    
    def test_is_retryable_http_error_non_http_error(self):
        """Test non-HttpError exceptions are not retryable"""
        error = ValueError("Not an HTTP error")
        assert is_retryable_http_error(error) is False
    
    def test_is_rate_limit_error(self):
        """Test rate limit error detection"""
        error_429 = create_http_error(429, "Rate Limit")
        assert is_rate_limit_error(error_429) is True
        
        error_500 = create_http_error(500, "Server Error")
        assert is_rate_limit_error(error_500) is False
    
    def test_is_server_error(self):
        """Test server error detection"""
        for status_code in [500, 502, 503, 504]:
            error = create_http_error(status_code, "Server Error")
            assert is_server_error(error) is True
        
        error_429 = create_http_error(429, "Rate Limit")
        assert is_server_error(error_429) is False
    
    def test_is_retryable_error_code(self):
        """Test retryable error code detection"""
        # Retryable codes
        for code in [429, 500, 502, 503, 504]:
            assert is_retryable_error_code(code) is True
        
        # Non-retryable codes
        for code in [200, 400, 401, 403, 404]:
            assert is_retryable_error_code(code) is False


# ============================================
# TEST RETRY DECORATORS
# ============================================

class TestRetryDecorators:
    """Test retry decorators"""
    
    def test_retry_gmail_api_success(self):
        """Test successful Gmail API call (no retry needed)"""
        @retry_gmail_api(max_attempts=3)
        def successful_call():
            return {"success": True}
        
        result = successful_call()
        assert result == {"success": True}
    
    def test_retry_gmail_api_retries_on_rate_limit(self):
        """Test Gmail API retries on rate limit error"""
        call_count = [0]
        
        @retry_gmail_api(max_attempts=3, min_wait=0.1, max_wait=0.5)
        def rate_limited_call():
            call_count[0] += 1
            if call_count[0] < 3:
                raise create_http_error(429, "Rate Limit")
            return {"success": True}
        
        result = rate_limited_call()
        assert result == {"success": True}
        assert call_count[0] == 3  # Failed twice, succeeded on 3rd attempt
    
    def test_retry_gmail_api_fails_on_non_retryable_error(self):
        """Test Gmail API does not retry on non-retryable errors"""
        call_count = [0]
        
        @retry_gmail_api(max_attempts=3)
        def non_retryable_error():
            call_count[0] += 1
            raise create_http_error(404, "Not Found")
        
        with pytest.raises(HttpError) as exc:
            non_retryable_error()
        
        assert call_count[0] == 1  # Should not retry
        assert exc.value.resp.status == 404
    
    def test_retry_gmail_api_max_attempts_exceeded(self):
        """Test Gmail API fails after max attempts"""
        call_count = [0]
        
        @retry_gmail_api(max_attempts=3, min_wait=0.1, max_wait=0.5)
        def always_fails():
            call_count[0] += 1
            raise create_http_error(503, "Service Unavailable")
        
        with pytest.raises(HttpError) as exc:
            always_fails()
        
        assert call_count[0] == 3  # Tried 3 times
        assert exc.value.resp.status == 503
    
    def test_retry_calendar_api_success(self):
        """Test successful Calendar API call"""
        @retry_calendar_api(max_attempts=3)
        def successful_call():
            return {"event": "created"}
        
        result = successful_call()
        assert result == {"event": "created"}
    
    def test_retry_calendar_api_retries_on_server_error(self):
        """Test Calendar API retries on server error"""
        call_count = [0]
        
        @retry_calendar_api(max_attempts=3, min_wait=0.1, max_wait=0.5)
        def server_error_call():
            call_count[0] += 1
            if call_count[0] < 2:
                raise create_http_error(500, "Internal Server Error")
            return {"success": True}
        
        result = server_error_call()
        assert result == {"success": True}
        assert call_count[0] == 2
    
    def test_retry_tasks_api_success(self):
        """Test successful Tasks API call"""
        @retry_tasks_api(max_attempts=3)
        def successful_call():
            return {"task": "created"}
        
        result = successful_call()
        assert result == {"task": "created"}
    
    def test_retry_generic_api_with_custom_exception(self):
        """Test generic retry with custom exception type"""
        call_count = [0]
        
        @retry_generic_api(max_attempts=3, min_wait=0.1, max_wait=0.5, retry_on=(ConnectionError,))
        def connection_error_call():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("Connection failed")
            return {"success": True}
        
        result = connection_error_call()
        assert result == {"success": True}
        assert call_count[0] == 2


# ============================================
# TEST RETRY CONFIG
# ============================================

class TestRetryConfig:
    """Test retry configuration"""
    
    def test_gmail_config(self):
        """Test Gmail retry configuration"""
        assert RetryConfig.GMAIL_MAX_ATTEMPTS == 5
        assert RetryConfig.GMAIL_MIN_WAIT == 1
        assert RetryConfig.GMAIL_MAX_WAIT == 60
        assert RetryConfig.GMAIL_MULTIPLIER == 2
    
    def test_calendar_config(self):
        """Test Calendar retry configuration"""
        assert RetryConfig.CALENDAR_MAX_ATTEMPTS == 5
        assert RetryConfig.CALENDAR_MIN_WAIT == 1
        assert RetryConfig.CALENDAR_MAX_WAIT == 60
        assert RetryConfig.CALENDAR_MULTIPLIER == 2
    
    def test_tasks_config(self):
        """Test Tasks retry configuration"""
        assert RetryConfig.TASKS_MAX_ATTEMPTS == 3
        assert RetryConfig.TASKS_MIN_WAIT == 1
        assert RetryConfig.TASKS_MAX_WAIT == 30
        assert RetryConfig.TASKS_MULTIPLIER == 2
    
    def test_default_config(self):
        """Test default retry configuration"""
        assert RetryConfig.DEFAULT_MAX_ATTEMPTS == 3
        assert RetryConfig.DEFAULT_MIN_WAIT == 1
        assert RetryConfig.DEFAULT_MAX_WAIT == 30
        assert RetryConfig.DEFAULT_MULTIPLIER == 2


# ============================================
# TEST EXPONENTIAL BACKOFF
# ============================================

class TestExponentialBackoff:
    """Test exponential backoff behavior"""
    
    def test_backoff_timing(self):
        """Test that retry delays follow exponential backoff"""
        import time
        call_times = []
        
        @retry_gmail_api(max_attempts=4, min_wait=0.1, max_wait=1)
        def failing_call():
            call_times.append(time.time())
            if len(call_times) < 4:
                raise create_http_error(503, "Service Unavailable")
            return {"success": True}
        
        result = failing_call()
        assert result == {"success": True}
        assert len(call_times) == 4
        
        # Check that delays increase (approximately)
        # First retry: ~0.1s, Second: ~0.2s, Third: ~0.4s
        if len(call_times) >= 3:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]
            # Second delay should be roughly 2x first delay (with some tolerance)
            assert delay2 > delay1 * 1.5


# ============================================
# TEST ERROR MESSAGES
# ============================================

class TestErrorMessages:
    """Test error logging and messages"""
    
    def test_non_retryable_error_message(self):
        """Test that non-retryable errors are logged correctly"""
        @retry_gmail_api(max_attempts=3)
        def bad_request():
            raise create_http_error(400, "Bad Request")
        
        with pytest.raises(HttpError) as exc:
            bad_request()
        
        assert "Bad Request" in str(exc.value)
    
    def test_max_attempts_error_message(self):
        """Test that max attempts errors are logged"""
        @retry_gmail_api(max_attempts=2, min_wait=0.1, max_wait=0.5)
        def always_fails():
            raise create_http_error(503, "Service Unavailable")
        
        with pytest.raises(HttpError) as exc:
            always_fails()
        
        assert exc.value.resp.status == 503


# ============================================
# INTEGRATION TESTS
# ============================================

class TestIntegration:
    """Integration tests with mock Google API"""
    
    def test_gmail_list_messages_with_retry(self):
        """Test Gmail list_messages with retry logic"""
        call_count = [0]
        
        @retry_gmail_api(max_attempts=3, min_wait=0.1, max_wait=0.5)
        def list_messages():
            call_count[0] += 1
            if call_count[0] < 2:
                # Simulate rate limit on first call
                raise create_http_error(429, "Rate Limit Exceeded")
            # Succeed on second call
            return {"messages": [{"id": "123"}]}
        
        result = list_messages()
        assert result == {"messages": [{"id": "123"}]}
        assert call_count[0] == 2
    
    def test_calendar_create_event_with_retry(self):
        """Test Calendar create_event with retry logic"""
        call_count = [0]
        
        @retry_calendar_api(max_attempts=3, min_wait=0.1, max_wait=0.5)
        def create_event():
            call_count[0] += 1
            if call_count[0] < 2:
                # Simulate server error
                raise create_http_error(500, "Internal Server Error")
            return {"id": "event123"}
        
        result = create_event()
        assert result == {"id": "event123"}
        assert call_count[0] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
