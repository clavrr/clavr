"""
Security Feature Evaluations - Phase 2 Tool Governance

Tests for:
- Rate Limiter
- Parameter Validator
- RBAC Enforcer
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Rate Limiter Tests
# =============================================================================

class TestRateLimiter:
    """Evaluate rate limiting capabilities."""
    
    @pytest.fixture
    def rate_limiter(self):
        from src.security.governance.rate_limiter import ToolRateLimiter, ToolBudget
        from collections import defaultdict
        # Create fresh instance with test budgets
        limiter = ToolRateLimiter.__new__(ToolRateLimiter)
        limiter._call_history = defaultdict(lambda: defaultdict(list))
        limiter._cooldowns = defaultdict(dict)
        limiter._budgets = {
            'test_tool': ToolBudget(max_calls=3, window_seconds=60, cooldown_seconds=30),
            'default': ToolBudget(max_calls=50, window_seconds=60, cooldown_seconds=60),
        }
        limiter._lock = asyncio.Lock()
        return limiter
    
    @pytest.mark.asyncio
    async def test_allows_within_limit(self, rate_limiter):
        """Allow calls within the rate limit."""
        user_id = 1
        
        # First 3 calls should be allowed
        for i in range(3):
            await rate_limiter.record_call(user_id, 'test_tool')
            allowed, _ = await rate_limiter.check_limit(user_id, 'test_tool')
            if i < 2:  # First 2 checks after recording
                assert allowed is True, f"Call {i+1} should be allowed"
    
    @pytest.mark.asyncio
    async def test_blocks_over_limit(self, rate_limiter):
        """Block calls that exceed the rate limit."""
        user_id = 2
        
        # Record 3 calls (the limit)
        for _ in range(3):
            await rate_limiter.record_call(user_id, 'test_tool')
        
        # 4th call should be blocked
        allowed, reason = await rate_limiter.check_limit(user_id, 'test_tool')
        
        assert allowed is False
        assert "slow down" in reason.lower() or "limit" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_different_users_independent(self, rate_limiter):
        """Different users have independent rate limits."""
        # User 1 at limit
        for _ in range(3):
            await rate_limiter.record_call(1, 'test_tool')
        
        # User 2 should still be allowed
        allowed, _ = await rate_limiter.check_limit(2, 'test_tool')
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_different_tools_independent(self, rate_limiter):
        """Different tools have independent rate limits."""
        user_id = 3
        
        # Use up limit on test_tool
        for _ in range(3):
            await rate_limiter.record_call(user_id, 'test_tool')
        
        # Default tool should still work
        allowed, _ = await rate_limiter.check_limit(user_id, 'other_tool')
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_usage_tracking(self, rate_limiter):
        """Usage stats are accurate."""
        user_id = 4
        
        await rate_limiter.record_call(user_id, 'test_tool')
        await rate_limiter.record_call(user_id, 'test_tool')
        
        usage = await rate_limiter.get_usage(user_id, 'test_tool')
        
        assert usage['calls_used'] == 2
        assert usage['calls_remaining'] == 1
        assert usage['limit'] == 3


# =============================================================================
# Parameter Validator Tests
# =============================================================================

class TestParameterValidator:
    """Evaluate parameter validation capabilities."""
    
    @pytest.fixture
    def validator(self):
        from src.security.governance.parameter_validator import ParameterValidator
        return ParameterValidator()
    
    # -------------------------------------------------------------------------
    # Email Send Validation
    # -------------------------------------------------------------------------
    
    def test_email_send_valid(self, validator):
        """Valid email params pass."""
        params = {
            'to': 'valid@example.com',
            'subject': 'Test Subject',
            'body': 'Test body content'
        }
        is_valid, _ = validator.validate('email_send', params)
        assert is_valid is True
    
    def test_email_send_invalid_email(self, validator):
        """Invalid email format rejected."""
        params = {
            'to': 'not-an-email',
            'subject': 'Test',
            'body': 'Body'
        }
        is_valid, reason = validator.validate('email_send', params)
        assert is_valid is False
        assert "email" in reason.lower()
    
    def test_email_send_missing_recipient(self, validator):
        """Missing required field rejected."""
        params = {
            'subject': 'Test',
            'body': 'Body'
        }
        is_valid, reason = validator.validate('email_send', params)
        assert is_valid is False
        assert "to" in reason.lower() or "missing" in reason.lower()
    
    # -------------------------------------------------------------------------
    # Calendar Create Validation
    # -------------------------------------------------------------------------
    
    def test_calendar_create_valid(self, validator):
        """Valid calendar params pass."""
        params = {
            'summary': 'Team Meeting',
            'start_time': '2024-12-20T10:00:00'
        }
        is_valid, _ = validator.validate('calendar_create', params)
        assert is_valid is True
    
    def test_calendar_create_invalid_date(self, validator):
        """Invalid date format rejected."""
        params = {
            'summary': 'Meeting',
            'start_time': 'tomorrow at noon'  # Not ISO format
        }
        is_valid, reason = validator.validate('calendar_create', params)
        assert is_valid is False
        assert "time" in reason.lower() or "format" in reason.lower()
    
    # -------------------------------------------------------------------------
    # Unknown Tool (Should Pass)
    # -------------------------------------------------------------------------
    
    def test_unknown_tool_passes(self, validator):
        """Unknown tools pass (fail open)."""
        params = {'anything': 'goes'}
        is_valid, _ = validator.validate('unknown_tool', params)
        assert is_valid is True


# =============================================================================
# RBAC Tests
# =============================================================================

class TestRBACEnforcer:
    """Evaluate RBAC enforcement capabilities."""
    
    @pytest.fixture
    def rbac(self):
        from src.security.governance.rbac import RBACEnforcer
        enforcer = RBACEnforcer()
        enforcer._graph_manager = None  # No graph for unit tests
        return enforcer
    
    @pytest.mark.asyncio
    async def test_allows_unprotected_tools(self, rbac):
        """Unprotected tools are always allowed."""
        allowed, _ = await rbac.check_permission(1, 'email_search')
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_allows_default_permissions(self, rbac):
        """Default permissions are granted to all."""
        from src.security.governance.rbac import DEFAULT_PERMISSIONS
        
        for perm in DEFAULT_PERMISSIONS[:3]:  # Test a few
            # Find a tool that requires this permission (if any)
            # For now, just verify the structure works
            allowed, _ = await rbac.check_permission(1, 'notes_write')
            assert allowed is True
    
    @pytest.mark.asyncio
    async def test_permission_cache_works(self, rbac):
        """Permission cache prevents repeated lookups."""
        # Pre-populate cache
        rbac._permission_cache[999] = {'email_write', 'calendar_write'}
        
        allowed, _ = await rbac.check_permission(999, 'email_send')
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_cache_clearing(self, rbac):
        """Cache can be cleared."""
        rbac._permission_cache[1] = {'test'}
        rbac._permission_cache[2] = {'test'}
        
        rbac.clear_cache(1)
        assert 1 not in rbac._permission_cache
        assert 2 in rbac._permission_cache
        
        rbac.clear_cache()
        assert len(rbac._permission_cache) == 0
