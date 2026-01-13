"""
Tool Rate Limiter for COR Layer

Provides per-user, per-tool rate limiting to prevent runaway API costs and spam.
This operates at the Agent/Tool layer, complementing the API-level rate limiter.
"""
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from src.utils.logger import setup_logger
from ..audit import SecurityAudit

logger = setup_logger(__name__)


@dataclass
class ToolBudget:
    """Configuration for a tool's rate limit budget"""
    max_calls: int           # Maximum calls allowed in window
    window_seconds: int      # Time window in seconds
    cooldown_seconds: int    # How long to wait after exceeding limit


# Default budgets per tool type (can be overridden via config)
DEFAULT_BUDGETS: Dict[str, ToolBudget] = {
    'email_send': ToolBudget(max_calls=5, window_seconds=300, cooldown_seconds=600),      # 5 emails per 5 min
    'email_search': ToolBudget(max_calls=30, window_seconds=60, cooldown_seconds=60),      # 30 searches per min
    'task_create': ToolBudget(max_calls=10, window_seconds=60, cooldown_seconds=120),    # 10 tasks per min
    'task_complete': ToolBudget(max_calls=20, window_seconds=60, cooldown_seconds=60),   # 20 completes per min
    'calendar_create': ToolBudget(max_calls=5, window_seconds=60, cooldown_seconds=120),  # 5 events per min
    'calendar_update': ToolBudget(max_calls=10, window_seconds=60, cooldown_seconds=60),
    'keep_create': ToolBudget(max_calls=15, window_seconds=60, cooldown_seconds=60),     # 15 notes per min
    'notion_create': ToolBudget(max_calls=10, window_seconds=60, cooldown_seconds=120),
    'default': ToolBudget(max_calls=50, window_seconds=60, cooldown_seconds=60),         # Default: 50/min
}


class ToolRateLimiter:
    """
    Per-user, per-tool rate limiter.
    
    Uses a sliding window counter algorithm for accurate limiting.
    Thread-safe for async operations.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'ToolRateLimiter':
        if cls._instance is None:
            cls._instance = ToolRateLimiter()
        return cls._instance
    
    def __init__(self, custom_budgets: Dict[str, ToolBudget] = None):
        # Structure: {user_id: {tool_name: [(timestamp, count), ...]}}
        self._call_history: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        # Structure: {user_id: {tool_name: cooldown_expires_at}}
        self._cooldowns: Dict[int, Dict[str, datetime]] = defaultdict(dict)
        self._budgets = {**DEFAULT_BUDGETS, **(custom_budgets or {})}
        self._lock = asyncio.Lock()
    
    def get_budget(self, tool_name: str) -> ToolBudget:
        """Get the budget for a tool, falling back to default."""
        return self._budgets.get(tool_name, self._budgets['default'])
    
    async def check_limit(self, user_id: int, tool_name: str) -> Tuple[bool, str]:
        """
        Check if a tool call is allowed under rate limits.
        
        Returns:
            (is_allowed, rejection_reason)
        """
        async with self._lock:
            now = datetime.utcnow()
            budget = self.get_budget(tool_name)
            
            # 1. Check cooldown
            cooldown_expires = self._cooldowns.get(user_id, {}).get(tool_name)
            if cooldown_expires and now < cooldown_expires:
                remaining = (cooldown_expires - now).seconds
                return False, f"Rate limit exceeded. Try again in {remaining} seconds."
            
            # 2. Clean old history and count recent calls
            window_start = now - timedelta(seconds=budget.window_seconds)
            history = self._call_history[user_id][tool_name]
            
            # Remove expired entries
            history[:] = [(ts, c) for ts, c in history if ts > window_start]
            
            # Count calls in window
            total_calls = sum(c for _, c in history)
            
            if total_calls >= budget.max_calls:
                # Trigger cooldown
                self._cooldowns[user_id][tool_name] = now + timedelta(seconds=budget.cooldown_seconds)
                
                # Audit log
                SecurityAudit.log_event(
                    event_type="RATE_LIMIT_TOOL",
                    status="BLOCKED",
                    severity="WARNING",
                    user_id=user_id,
                    details={
                        "tool": tool_name,
                        "calls_made": total_calls,
                        "limit": budget.max_calls,
                        "window_seconds": budget.window_seconds
                    }
                )
                
                logger.warning(f"Rate limit exceeded for user {user_id} on tool {tool_name}")
                return False, f"Too many {tool_name} operations. Please slow down."
            
            return True, ""
    
    async def record_call(self, user_id: int, tool_name: str):
        """Record a successful tool call."""
        async with self._lock:
            now = datetime.utcnow()
            self._call_history[user_id][tool_name].append((now, 1))
    
    async def get_usage(self, user_id: int, tool_name: str) -> Dict:
        """Get current usage stats for a user's tool."""
        async with self._lock:
            budget = self.get_budget(tool_name)
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=budget.window_seconds)
            
            history = self._call_history.get(user_id, {}).get(tool_name, [])
            recent = [(ts, c) for ts, c in history if ts > window_start]
            total_calls = sum(c for _, c in recent)
            
            return {
                "calls_used": total_calls,
                "calls_remaining": max(0, budget.max_calls - total_calls),
                "limit": budget.max_calls,
                "window_seconds": budget.window_seconds
            }
