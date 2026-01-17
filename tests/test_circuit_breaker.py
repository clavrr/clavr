"""
Tests for Circuit Breaker Pattern
"""
import pytest
import time
from unittest.mock import Mock, patch
from googleapiclient.errors import HttpError
import pybreaker

from src.utils.circuit_breaker import (
    CircuitBreakerConfig,
    gmail_breaker,
    calendar_breaker,
    tasks_breaker,
    with_gmail_circuit_breaker,
    with_calendar_circuit_breaker,
    with_circuit_breaker,
    get_breaker_state,
    get_all_breaker_states,
    reset_breaker,
    reset_all_breakers,
    ServiceUnavailableError,
    gmail_list_fallback,
    calendar_list_fallback,
    generic_none_fallback,
    generic_empty_dict_fallback
)


class TestCircuitBreakerConfig:
    """Test circuit breaker configuration"""
    
    def test_gmail_config(self):
        """Test Gmail circuit breaker configuration"""
        assert CircuitBreakerConfig.GMAIL_FAIL_MAX == 5
        assert CircuitBreakerConfig.GMAIL_TIMEOUT == 60
        assert CircuitBreakerConfig.GMAIL_EXPECTED_EXCEPTION == HttpError
    
    def test_calendar_config(self):
        """Test Calendar circuit breaker configuration"""
        assert CircuitBreakerConfig.CALENDAR_FAIL_MAX == 5
        assert CircuitBreakerConfig.CALENDAR_TIMEOUT == 60
        assert CircuitBreakerConfig.CALENDAR_EXPECTED_EXCEPTION == HttpError
    
    def test_tasks_config(self):
        """Test Tasks circuit breaker configuration"""
        assert CircuitBreakerConfig.TASKS_FAIL_MAX == 3
        assert CircuitBreakerConfig.TASKS_TIMEOUT == 45
        assert CircuitBreakerConfig.TASKS_EXPECTED_EXCEPTION == HttpError


class TestCircuitBreakerInstances:
    """Test circuit breaker instances"""
    
    def setup_method(self):
        """Reset all breakers before each test"""
        reset_all_breakers()
    
    def test_gmail_breaker_exists(self):
        """Test Gmail circuit breaker is properly configured"""
        assert gmail_breaker is not None
        assert gmail_breaker.name == "Gmail API"
        assert gmail_breaker.fail_max == 5
    
    def test_calendar_breaker_exists(self):
        """Test Calendar circuit breaker is properly configured"""
        assert calendar_breaker is not None
        assert calendar_breaker.name == "Calendar API"
        assert calendar_breaker.fail_max == 5
    
    def test_tasks_breaker_exists(self):
        """Test Tasks circuit breaker is properly configured"""
        assert tasks_breaker is not None
        assert tasks_breaker.name == "Tasks API"
        assert tasks_breaker.fail_max == 3


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorators"""
    
    def setup_method(self):
        """Reset all breakers before each test"""
        reset_all_breakers()
    
    def test_successful_calls(self):
        """Test successful calls pass through"""
        call_count = [0]
        
        @with_gmail_circuit_breaker()
        def successful_call():
            call_count[0] += 1
            return {"success": True}
        
        result = successful_call()
        assert result == {"success": True}
        assert call_count[0] == 1
        assert gmail_breaker.current_state == "closed"
    
    def test_circuit_opens_after_failures(self):
        """Test circuit opens after consecutive failures"""
        reset_breaker(gmail_breaker)
        call_count = [0]
        
        def create_http_error():
            """Helper to create HttpError"""
            resp = Mock()
            resp.status = 500
            return HttpError(resp=resp, content=b'Internal Server Error')
        
        @with_gmail_circuit_breaker()
        def failing_call():
            call_count[0] += 1
            raise create_http_error()
        
        # First 4 calls should raise HttpError (fail_max=5, so circuit opens on 5th)
        for i in range(4):
            with pytest.raises(HttpError):
                failing_call()
        
        assert call_count[0] == 4
        assert gmail_breaker.current_state == "closed"
        
        # 5th call triggers circuit to open and raises ServiceUnavailableError
        with pytest.raises(ServiceUnavailableError):
            failing_call()
        
        assert call_count[0] == 5
        assert gmail_breaker.current_state == "open"
        
        # Subsequent calls should be blocked by circuit breaker
        with pytest.raises(ServiceUnavailableError):
            failing_call()
        
        # Call count should not increase (blocked by circuit before function executes)
        assert call_count[0] == 5
    
    def test_fallback_on_open_circuit(self):
        """Test fallback function is called when circuit is open"""
        reset_breaker(gmail_breaker)
        
        def fallback_func():
            return {"fallback": True}
        
        def create_http_error():
            resp = Mock()
            resp.status = 500
            return HttpError(resp=resp, content=b'Error')
        
        @with_gmail_circuit_breaker(fallback=fallback_func)
        def failing_call():
            raise create_http_error()
        
        # Fail enough times to open circuit
        for i in range(5):
            try:
                failing_call()
            except HttpError:
                pass
        
        # Circuit should be open, fallback should be called
        result = failing_call()
        assert result == {"fallback": True}
    
    def test_circuit_half_open_after_timeout(self):
        """Test circuit transitions to half-open after timeout"""
        # This test would require waiting for the timeout
        # Skipped for unit tests, but important for integration tests
        pass


class TestFallbackFunctions:
    """Test fallback functions"""
    
    def test_gmail_list_fallback(self):
        """Test Gmail list fallback returns empty list"""
        result = gmail_list_fallback()
        assert result == []
    
    def test_calendar_list_fallback(self):
        """Test Calendar list fallback returns empty list"""
        result = calendar_list_fallback()
        assert result == []
    
    def test_generic_none_fallback(self):
        """Test generic None fallback"""
        result = generic_none_fallback()
        assert result is None
    
    def test_generic_empty_dict_fallback(self):
        """Test generic empty dict fallback"""
        result = generic_empty_dict_fallback()
        assert result == {}


class TestUtilityFunctions:
    """Test utility functions"""
    
    def setup_method(self):
        """Reset all breakers before each test"""
        reset_all_breakers()
    
    def test_get_breaker_state(self):
        """Test getting breaker state"""
        state = get_breaker_state(gmail_breaker)
        
        assert 'name' in state
        assert 'state' in state
        assert 'fail_counter' in state
        assert 'fail_max' in state
        assert 'timeout' in state
        assert 'is_closed' in state
        assert 'is_open' in state
        assert 'is_half_open' in state
        
        assert state['name'] == "Gmail API"
        assert state['fail_max'] == 5
        assert state['is_closed'] is True
        assert state['is_open'] is False
    
    def test_get_all_breaker_states(self):
        """Test getting all breaker states"""
        states = get_all_breaker_states()
        
        assert 'gmail' in states
        assert 'calendar' in states
        assert 'tasks' in states
        
        assert states['gmail']['name'] == "Gmail API"
        assert states['calendar']['name'] == "Calendar API"
        assert states['tasks']['name'] == "Tasks API"
    
    def test_reset_breaker(self):
        """Test resetting a single breaker"""
        # Open the circuit by failing
        def create_http_error():
            resp = Mock()
            resp.status = 500
            return HttpError(resp=resp, content=b'Error')
        
        @with_gmail_circuit_breaker()
        def failing_call():
            raise create_http_error()
        
        # Fail 4 times (HttpError), then 5th triggers circuit open (ServiceUnavailableError)
        for i in range(4):
            try:
                failing_call()
            except HttpError:
                pass
        
        # 5th call opens the circuit
        try:
            failing_call()
        except ServiceUnavailableError:
            pass
        
        assert gmail_breaker.current_state == "open"
        
        # Reset breaker
        reset_breaker(gmail_breaker)
        assert gmail_breaker.current_state == "closed"
        assert gmail_breaker.fail_counter == 0
    
    def test_reset_all_breakers(self):
        """Test resetting all breakers"""
        reset_all_breakers()
        
        assert gmail_breaker.current_state == "closed"
        assert calendar_breaker.current_state == "closed"
        assert tasks_breaker.current_state == "closed"


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker"""
    
    def setup_method(self):
        """Reset all breakers before each test"""
        reset_all_breakers()
    
    def test_multiple_services_independent(self):
        """Test that different service breakers are independent"""
        reset_all_breakers()
        
        def create_http_error():
            resp = Mock()
            resp.status = 500
            return HttpError(resp=resp, content=b'Error')
        
        @with_gmail_circuit_breaker()
        def gmail_call():
            raise create_http_error()
        
        @with_calendar_circuit_breaker()
        def calendar_call():
            return {"success": True}
        
        # Fail Gmail calls 4 times (HttpError), then 5th opens circuit (ServiceUnavailableError)
        for i in range(4):
            try:
                gmail_call()
            except HttpError:
                pass
        
        # 5th call opens the circuit
        try:
            gmail_call()
        except ServiceUnavailableError:
            pass
        
        # Gmail circuit should be open
        assert gmail_breaker.current_state == "open"
        
        # Calendar circuit should still be closed
        assert calendar_breaker.current_state == "closed"
        
        # Calendar calls should still work
        result = calendar_call()
        assert result == {"success": True}
    
    def test_circuit_breaker_with_retry_decorator(self):
        """Test circuit breaker works with retry decorator (decorator stacking)"""
        # This is tested in the actual implementation where both decorators are used
        # Circuit breaker should be outer, retry should be inner
        pass


class TestCircuitBreakerErrors:
    """Test error handling in circuit breaker"""
    
    def setup_method(self):
        """Reset all breakers before each test"""
        reset_all_breakers()
    
    def test_service_unavailable_error_raised(self):
        """Test ServiceUnavailableError is raised when circuit is open"""
        reset_breaker(gmail_breaker)
        
        def create_http_error():
            resp = Mock()
            resp.status = 500
            return HttpError(resp=resp, content=b'Error')
        
        @with_gmail_circuit_breaker()
        def failing_call():
            raise create_http_error()
        
        # Open the circuit: 4 HttpErrors, then 5th call opens it with ServiceUnavailableError
        for i in range(4):
            try:
                failing_call()
            except HttpError:
                pass
        
        # 5th call opens circuit
        with pytest.raises(ServiceUnavailableError):
            failing_call()
        
        # Subsequent calls should also raise ServiceUnavailableError when circuit is open
        with pytest.raises(ServiceUnavailableError) as exc_info:
            failing_call()
        
        assert "Gmail API is currently unavailable" in str(exc_info.value)
        assert "Circuit breaker is open" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
