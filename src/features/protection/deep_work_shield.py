"""
Deep Work Shield Agent

Ghost Agent that automatically activates Deep Work mode when:
1. User has many open Linear tickets (threshold: 5)
2. Calendar is relatively free (good opportunity for focus)

When triggered, it:
1. Blocks calendar for 2 hours
2. Sets Slack status to "Heads-down"
3. Posts a status message to relevant channels
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


@dataclass
class DeepWorkContext:
    """Context for deep work shield decision."""
    open_issue_count: int
    high_priority_count: int
    top_issue_id: Optional[str] = None
    top_issue_title: Optional[str] = None
    is_calendar_free: bool = False
    current_protection_level: str = "normal"


class DeepWorkShieldAgent:
    """
    Ghost Agent for automatic Deep Work Shield activation.
    
    This agent runs periodically (every 30 min) and checks:
    1. How many Linear tickets are assigned to the user
    2. Whether the calendar has free time for focus
    
    If conditions are met, it automatically:
    1. Creates a calendar block
    2. Sets Slack status
    3. Posts status message
    
    All actions go through ActionExecutor to respect user autonomy settings.
    """
    
    # Configuration thresholds
    ISSUE_THRESHOLD = 5  # Trigger when >= 5 open issues
    FOCUS_DURATION_MINUTES = 120  # 2 hours of focus time
    
    def __init__(self, config: Config, credential_factory: Any = None):
        self.config = config
        self.factory = credential_factory
        
    async def check_and_activate(
        self, 
        user_id: int, 
        db_session: Any
    ) -> Dict[str, Any]:
        """
        Main entry point: Check conditions and activate if appropriate.
        
        Returns:
            Dict with status and any actions taken
        """
        try:
            # 1. Gather context
            context = await self._gather_context(user_id, db_session)
            
            logger.info(
                f"[DeepWorkShield] Context for user {user_id}: "
                f"{context.open_issue_count} issues, "
                f"calendar_free={context.is_calendar_free}, "
                f"protection={context.current_protection_level}"
            )
            
            # 2. Check if we should activate
            should_activate = self._should_activate(context)
            
            if not should_activate:
                return {
                    "status": "skipped",
                    "reason": self._get_skip_reason(context),
                    "context": {
                        "open_issues": context.open_issue_count,
                        "calendar_free": context.is_calendar_free,
                    }
                }
            
            # 3. Execute deep work shield
            result = await self._activate_shield(user_id, context, db_session)
            
            return {
                "status": "activated",
                "actions": result,
                "context": {
                    "open_issues": context.open_issue_count,
                    "top_issue": context.top_issue_title,
                }
            }
            
        except Exception as e:
            logger.error(f"[DeepWorkShield] Error: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    async def _gather_context(
        self, 
        user_id: int, 
        db_session: Any
    ) -> DeepWorkContext:
        """Gather context from Linear and Calendar."""
        context = DeepWorkContext(
            open_issue_count=0,
            high_priority_count=0,
            is_calendar_free=False,
            current_protection_level="normal"
        )
        
        # Get Linear issues
        try:
            from src.integrations.linear.service import LinearService
            linear = LinearService(self.config)
            
            if linear.is_available():
                issues = await linear.get_my_issues(state="active", limit=20)
                context.open_issue_count = len(issues) if issues else 0
                
                # Count high priority
                for issue in (issues or []):
                    priority = issue.get('priority', 0)
                    if priority >= 3:  # High priority
                        context.high_priority_count += 1
                
                # Get top issue for status message
                if issues:
                    top = issues[0]
                    context.top_issue_id = top.get('identifier', top.get('id'))
                    context.top_issue_title = top.get('title', '')[:50]
                    
        except Exception as e:
            logger.warning(f"[DeepWorkShield] Linear unavailable: {e}")
        
        # Check calendar availability
        try:
            if self.factory:
                calendar = self.factory.create_service('calendar', user_id=user_id, db_session=db_session)
                
                now = datetime.utcnow()
                end = now + timedelta(hours=2)
                
                # Check if next 2 hours are free
                free_slots = calendar.find_free_time(
                    duration_minutes=self.FOCUS_DURATION_MINUTES,
                    start_date=now.isoformat(),
                    end_date=end.isoformat(),
                    max_suggestions=1
                )
                
                context.is_calendar_free = len(free_slots) > 0
                
        except Exception as e:
            logger.warning(f"[DeepWorkShield] Calendar unavailable: {e}")
        
        # Check current protection level
        try:
            from src.features.protection.deep_work import DeepWorkLogic, ProtectionLevel
            
            if self.factory:
                calendar = self.factory.create_service('calendar', user_id=user_id, db_session=db_session)
                now = datetime.utcnow()
                events = calendar.list_events(
                    start_date=now.isoformat(),
                    end_date=(now + timedelta(hours=2)).isoformat()
                )
                
                busyness = DeepWorkLogic.calculate_busyness_score(
                    events or [],
                    now,
                    now + timedelta(hours=2)
                )
                level = DeepWorkLogic.determine_protection_level(busyness, events)
                context.current_protection_level = level.value
                
        except Exception as e:
            logger.warning(f"[DeepWorkShield] Protection level check failed: {e}")
        
        return context
    
    def _should_activate(self, context: DeepWorkContext) -> bool:
        """Determine if we should activate the shield."""
        # Already in deep work mode
        if context.current_protection_level == "deep_work":
            return False
        
        # High meeting density - not a good time
        if context.current_protection_level == "meeting_heavy":
            return False
        
        # Need enough issues to warrant focus time
        if context.open_issue_count < self.ISSUE_THRESHOLD:
            return False
        
        # Need free calendar time
        if not context.is_calendar_free:
            return False
        
        return True
    
    def _get_skip_reason(self, context: DeepWorkContext) -> str:
        """Get human-readable reason for skipping."""
        if context.current_protection_level == "deep_work":
            return "Already in Deep Work mode"
        if context.current_protection_level == "meeting_heavy":
            return "Too many meetings right now"
        if context.open_issue_count < self.ISSUE_THRESHOLD:
            return f"Only {context.open_issue_count} issues (need {self.ISSUE_THRESHOLD}+)"
        if not context.is_calendar_free:
            return "Calendar not free for focus block"
        return "Unknown"
    
    async def _activate_shield(
        self, 
        user_id: int, 
        context: DeepWorkContext,
        db_session: Any
    ) -> List[Dict[str, Any]]:
        """Execute the Deep Work Shield actions."""
        from src.ai.autonomy.action_executor import ActionExecutor
        
        executor = ActionExecutor(db_session, self.config, self.factory)
        results = []
        
        now = datetime.utcnow()
        end_time = now + timedelta(minutes=self.FOCUS_DURATION_MINUTES)
        
        # Compose status message
        issue_ref = f" on {context.top_issue_id}" if context.top_issue_id else ""
        status_text = f"Heads-down{issue_ref}. Back at {end_time.strftime('%I:%M %p')}"
        
        # 1. Block Calendar
        calendar_plan = {
            "type": "calendar_block",
            "description": f"Focus Time: {context.open_issue_count} Linear tickets",
            "params": {
                "start": now.isoformat(),
                "duration_minutes": self.FOCUS_DURATION_MINUTES,
                "summary": f"🛡️ Deep Work (Auto-blocked by Clavr)",
                "description": f"Focus time for {context.open_issue_count} Linear tickets"
            }
        }
        
        result = await executor.execute_plan(calendar_plan, user_id)
        results.append({
            "action": "calendar_block",
            "status": result.status,
            "action_id": result.action_id,
        })
        
        # 2. Set Slack Status
        slack_status_plan = {
            "type": "slack_status",
            "description": f"Set Slack status: {status_text}",
            "params": {
                "status_text": status_text,
                "status_emoji": ":shield:",
                "expiration_minutes": self.FOCUS_DURATION_MINUTES,
            }
        }
        
        result = await executor.execute_plan(slack_status_plan, user_id)
        results.append({
            "action": "slack_status",
            "status": result.status,
            "action_id": result.action_id,
        })
        
        logger.info(
            f"[DeepWorkShield] ✅ Activated for user {user_id}: "
            f"{context.open_issue_count} issues, {self.FOCUS_DURATION_MINUTES}min block"
        )
        
        return results


async def run_deep_work_check(user_id: int, config: Config, db_session: Any, factory: Any = None):
    """
    Convenience function to run deep work check for a user.
    Called by Celery task.
    """
    agent = DeepWorkShieldAgent(config, factory)
    return await agent.check_and_activate(user_id, db_session)
