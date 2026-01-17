"""
Conflict Detector Service

Detects conflicts between calendar events and Linear deadlines.

When a user schedules a meeting that overlaps with a high-priority Linear deadline,
this service:
1. Detects the conflict
2. Notifies the user via NotificationService
3. Optionally suggests rescheduling via ActionExecutor
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


@dataclass
class ConflictInfo:
    """Information about a detected conflict."""
    event_id: str
    event_title: str
    event_start: datetime
    event_end: datetime
    issue_id: str
    issue_title: str
    issue_priority: int
    deadline: datetime
    conflict_type: str  # 'overlap', 'same_day', 'day_before'
    severity: str  # 'critical', 'high', 'medium'


class ConflictDetector:
    """
    Detects conflicts between calendar events and Linear deadlines.
    
    Usage:
        detector = ConflictDetector(config, linear_service)
        conflicts = await detector.check_event_for_conflicts(event, user_id)
    """
    
    def __init__(
        self, 
        config: Config, 
        linear_service: Any = None,
        calendar_service: Any = None
    ):
        self.config = config
        self.linear = linear_service
        self.calendar = calendar_service
        
    async def check_event_for_conflicts(
        self, 
        event: Dict[str, Any],
        user_id: int
    ) -> List[ConflictInfo]:
        """
        Check if a calendar event conflicts with any high-priority Linear deadlines.
        
        Called when:
        - New event is created (webhook: calendar.event.created)
        - Event is updated (webhook: calendar.event.updated)
        
        Args:
            event: Google Calendar event dict
            user_id: User ID for the event owner
            
        Returns:
            List of ConflictInfo for any detected conflicts
        """
        conflicts = []
        
        try:
            # 1. Parse event time
            event_start, event_end = self._parse_event_times(event)
            if not event_start or not event_end:
                return []
            
            event_title = event.get('summary', 'Untitled Event')
            event_id = event.get('id', '')
            
            # 2. Get high priority Linear deadlines
            if not self.linear:
                from src.integrations.linear.service import LinearService
                self.linear = LinearService(self.config)
            
            if not self.linear.is_available():
                logger.debug("[ConflictDetector] Linear not available, skipping")
                return []
            
            # Look 30 days ahead for deadlines
            hp_issues = await self.linear.get_high_priority_deadlines(days_ahead=30)
            
            if not hp_issues:
                return []
            
            # 3. Check each issue for conflicts
            for issue in hp_issues:
                due_date_str = issue.get('dueDate')
                if not due_date_str:
                    continue
                    
                try:
                    deadline = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                except ValueError:
                    continue
                
                # Check for conflict
                conflict = self._check_conflict(
                    event_start, event_end, event_title, event_id,
                    deadline, issue
                )
                
                if conflict:
                    conflicts.append(conflict)
            
            if conflicts:
                logger.info(
                    f"[ConflictDetector] Found {len(conflicts)} conflict(s) for event '{event_title}'"
                )
            
            return conflicts
            
        except Exception as e:
            logger.error(f"[ConflictDetector] Error checking conflicts: {e}", exc_info=True)
            return []
    
    def _parse_event_times(self, event: Dict[str, Any]) -> tuple[Optional[datetime], Optional[datetime]]:
        """Parse event start and end times."""
        try:
            start = event.get('start', {})
            end = event.get('end', {})
            
            # Handle all-day events
            if 'date' in start:
                start_dt = datetime.fromisoformat(start['date'])
                end_dt = datetime.fromisoformat(end.get('date', start['date']))
            elif 'dateTime' in start:
                start_dt = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
            else:
                return None, None
            
            return start_dt, end_dt
            
        except Exception as e:
            logger.warning(f"[ConflictDetector] Failed to parse event times: {e}")
            return None, None
    
    def _check_conflict(
        self,
        event_start: datetime,
        event_end: datetime,
        event_title: str,
        event_id: str,
        deadline: datetime,
        issue: Dict[str, Any]
    ) -> Optional[ConflictInfo]:
        """Check if an event conflicts with a deadline."""
        issue_id = issue.get('identifier', issue.get('id', ''))
        issue_title = issue.get('title', '')
        priority = issue.get('priority', 0)
        
        # Normalize to dates for comparison
        event_date = event_start.date()
        deadline_date = deadline.date()
        
        conflict_type = None
        severity = None
        
        # Critical: Event is on the deadline day
        if event_date == deadline_date:
            conflict_type = 'same_day'
            severity = 'critical'
        
        # High: Event is the day before deadline
        elif event_date == deadline_date - timedelta(days=1):
            event_hours = (event_end - event_start).total_seconds() / 3600
            if event_hours >= 1:  # Only count meetings >= 1 hour
                conflict_type = 'day_before'
                severity = 'high'
        
        # Medium: Event overlaps with deadline (within 2 days)
        elif abs((event_date - deadline_date).days) <= 2:
            # Check if it's a long meeting that could impact work
            event_hours = (event_end - event_start).total_seconds() / 3600
            if event_hours >= 2:  # Long meetings (2+ hours) within 2 days
                conflict_type = 'overlap'
                severity = 'medium'
        
        if conflict_type:
            return ConflictInfo(
                event_id=event_id,
                event_title=event_title,
                event_start=event_start,
                event_end=event_end,
                issue_id=issue_id,
                issue_title=issue_title,
                issue_priority=priority,
                deadline=deadline,
                conflict_type=conflict_type,
                severity=severity,
            )
        
        return None
    
    async def handle_conflicts(
        self,
        conflicts: List[ConflictInfo],
        user_id: int,
        db_session: Any
    ) -> Dict[str, Any]:
        """
        Handle detected conflicts by notifying user and optionally suggesting reschedule.
        
        Args:
            conflicts: List of detected conflicts
            user_id: User to notify
            db_session: Database session for NotificationService
            
        Returns:
            Dict with actions taken
        """
        if not conflicts:
            return {"status": "no_conflicts"}
        
        try:
            from src.services.notifications import (
                NotificationService,
                NotificationRequest,
                NotificationType,
                NotificationPriority,
            )
            
            results = []
            notification_service = NotificationService(db_session)
            
            for conflict in conflicts:
                # Determine notification priority based on severity
                if conflict.severity == 'critical':
                    priority = NotificationPriority.URGENT
                elif conflict.severity == 'high':
                    priority = NotificationPriority.HIGH
                else:
                    priority = NotificationPriority.NORMAL
                
                # Build notification message
                message = self._build_conflict_message(conflict)
                
                # Send notification
                request = NotificationRequest(
                    user_id=user_id,
                    title=f"⚠️ Calendar Conflict: {conflict.issue_id}",
                    message=message,
                    notification_type=NotificationType.SYSTEM,
                    priority=priority,
                    icon="alert-triangle",
                    action_url=f"/calendar?event={conflict.event_id}",
                    action_label="View Event",
                    expires_in_hours=48,
                )
                
                await notification_service.send_notification(request)
                
                results.append({
                    "event": conflict.event_title,
                    "issue": conflict.issue_id,
                    "severity": conflict.severity,
                    "notified": True,
                })
            
            logger.info(f"[ConflictDetector] Notified user {user_id} about {len(conflicts)} conflict(s)")
            
            return {
                "status": "notified",
                "conflicts": len(conflicts),
                "details": results,
            }
            
        except Exception as e:
            logger.error(f"[ConflictDetector] Failed to handle conflicts: {e}")
            return {"status": "error", "error": str(e)}
    
    def _build_conflict_message(self, conflict: ConflictInfo) -> str:
        """Build human-readable conflict message."""
        deadline_str = conflict.deadline.strftime("%b %d")
        event_time = conflict.event_start.strftime("%b %d at %I:%M %p")
        
        if conflict.conflict_type == 'same_day':
            return (
                f"Your meeting '{conflict.event_title}' ({event_time}) is on the same day "
                f"as the deadline for high-priority issue {conflict.issue_id}: "
                f"'{conflict.issue_title}'. Consider rescheduling to protect your focus time."
            )
        elif conflict.conflict_type == 'day_before':
            return (
                f"Your meeting '{conflict.event_title}' ({event_time}) is the day before "
                f"the deadline for {conflict.issue_id}: '{conflict.issue_title}' "
                f"(due {deadline_str}). This may impact your ability to finish on time."
            )
        else:
            return (
                f"Long meeting '{conflict.event_title}' ({event_time}) may conflict with "
                f"high-priority deadline: {conflict.issue_id} '{conflict.issue_title}' "
                f"(due {deadline_str})."
            )


async def check_calendar_event_for_conflicts(
    event: Dict[str, Any],
    user_id: int,
    config: Config,
    db_session: Any
) -> Dict[str, Any]:
    """
    Convenience function for webhook handlers.
    
    Call this when a calendar event is created/updated.
    """
    detector = ConflictDetector(config)
    conflicts = await detector.check_event_for_conflicts(event, user_id)
    
    if conflicts:
        return await detector.handle_conflicts(conflicts, user_id, db_session)
    
    return {"status": "no_conflicts"}
