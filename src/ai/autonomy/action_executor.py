"""
ActionExecutor - Execute planned actions based on user autonomy settings.

This is the central execution engine for all autonomous actions.
It handles:
- Autonomy level checking
- Action execution via service APIs
- Approval workflow for LOW autonomy
- Undo functionality (5-minute window)
- Notification dispatch (email + in-app/push)
- Audit logging
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models import AutonomySettings, AutonomousAction, User
from src.utils.logger import setup_logger
from src.utils.config import Config
from .autonomy_defaults import (
    ActionType, 
    AutonomyLevel, 
    DEFAULT_AUTONOMY_LEVELS,
    UNDO_WINDOW_MINUTES,
    is_action_undoable,
)

logger = setup_logger(__name__)


@dataclass
class ExecutionResult:
    """Result of an action execution attempt."""
    success: bool
    status: str  # 'executed', 'pending_approval', 'failed', 'queued'
    action_id: int
    result_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    undo_available_until: Optional[str] = None  # ISO timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ActionExecutor:
    """
    Central executor for autonomous actions.
    
    Flow:
    1. Receive plan from ProactivePlanner or Ghost Agent
    2. Check user's autonomy level for action type
    3. Execute or queue based on level
    4. Log to AutonomousAction table
    5. Notify user if required
    
    Usage:
        executor = ActionExecutor(db, config, credential_factory)
        result = await executor.execute_plan(plan, user_id)
    """
    
    def __init__(
        self, 
        db_session: AsyncSession, 
        config: Config, 
        credential_factory: Any = None
    ):
        self.db = db_session
        self.config = config
        self.factory = credential_factory
        
    async def execute_plan(
        self, 
        plan: Dict[str, Any], 
        user_id: int
    ) -> ExecutionResult:
        """
        Execute a plan based on user's autonomy settings.
        
        Args:
            plan: ActionPlan dict with 'type', 'description', 'params'
            user_id: User ID to execute for
            
        Returns:
            ExecutionResult with status and action_id
        """
        action_type = plan.get('type')
        
        if not action_type:
            logger.error("[ActionExecutor] Plan missing 'type' field")
            return ExecutionResult(
                success=False,
                status='failed',
                action_id=0,
                error="Plan missing 'type' field"
            )
        
        # 1. Get autonomy level for this action type
        level = await self._get_autonomy_level(user_id, action_type)
        logger.info(f"[ActionExecutor] Action '{action_type}' for user {user_id}: autonomy={level}")
        
        # 2. Create action record
        action = await self._create_action_record(user_id, plan, level)
        
        # 3. Execute based on level
        if level == AutonomyLevel.HIGH.value:
            result = await self._execute_action(action, plan, user_id)
            if result.success:
                await self._notify_user_after(action, plan, user_id)
            return result
            
        elif level == AutonomyLevel.MEDIUM.value:
            await self._notify_user_before(action, plan, user_id)
            return await self._execute_action(action, plan, user_id)
            
        else:  # LOW
            await self._request_approval(action, plan, user_id)
            return ExecutionResult(
                success=True,
                status='pending_approval',
                action_id=action.id
            )
    
    async def _get_autonomy_level(self, user_id: int, action_type: str) -> str:
        """Get user's autonomy level for an action type."""
        try:
            stmt = select(AutonomySettings).where(
                AutonomySettings.user_id == user_id,
                AutonomySettings.action_type == action_type
            )
            result = await self.db.execute(stmt)
            setting = result.scalar_one_or_none()
            
            if setting:
                return setting.autonomy_level
                
        except Exception as e:
            logger.warning(f"[ActionExecutor] Failed to get autonomy setting: {e}")
        
        # Fall back to default
        return DEFAULT_AUTONOMY_LEVELS.get(action_type, AutonomyLevel.LOW.value)
    
    async def _create_action_record(
        self, 
        user_id: int, 
        plan: Dict[str, Any], 
        autonomy_level: str
    ) -> AutonomousAction:
        """Create an action record in the database."""
        action_type = plan.get('type')
        undoable = is_action_undoable(action_type)
        requires_approval = autonomy_level == AutonomyLevel.LOW.value
        
        action = AutonomousAction(
            user_id=user_id,
            action_type=action_type,
            plan_data=plan,
            goal_id=plan.get('goal_id'),
            status='pending' if requires_approval else 'queued',
            autonomy_level_used=autonomy_level,
            requires_approval=requires_approval,
            is_undoable=undoable,
        )
        
        self.db.add(action)
        await self.db.commit()
        await self.db.refresh(action)
        
        logger.debug(f"[ActionExecutor] Created action record: id={action.id}")
        return action
    
    async def _execute_action(
        self, 
        action: AutonomousAction, 
        plan: Dict[str, Any], 
        user_id: int
    ) -> ExecutionResult:
        """Actually execute the action via service APIs."""
        action_type = plan.get('type')
        params = plan.get('params', {})
        
        try:
            result = {}
            undo_data = {}
            
            # Route to appropriate executor
            if action_type in ['calendar_block', 'calendar_event']:
                result, undo_data = await self._execute_calendar(params, user_id)
            elif action_type == 'email_draft':
                result, undo_data = await self._execute_email_draft(params, user_id)
            elif action_type == 'email_send':
                result, undo_data = await self._execute_email_send(params, user_id)
            elif action_type == 'task_create':
                result, undo_data = await self._execute_task_create(params, user_id)
            elif action_type == 'linear_issue':
                result, undo_data = await self._execute_linear_issue(params, user_id)
            elif action_type == 'slack_message':
                result, undo_data = await self._execute_slack_message(params, user_id)
            elif action_type == 'slack_status':
                result, undo_data = await self._execute_slack_status(params, user_id)
            else:
                raise ValueError(f"Unknown action type: {action_type}")
            
            # Update action record
            action.status = 'executed'
            action.executed_at = datetime.utcnow()
            action.result = result
            action.approved_by = 'auto' if action.autonomy_level_used != AutonomyLevel.LOW.value else 'user'
            action.approved_at = datetime.utcnow()
            
            # Set undo window if applicable
            undo_until = None
            if action.is_undoable and undo_data:
                action.undo_data = undo_data
                action.undo_expires_at = datetime.utcnow() + timedelta(minutes=UNDO_WINDOW_MINUTES)
                undo_until = action.undo_expires_at.isoformat()
            
            await self.db.commit()
            
            logger.info(f"[ActionExecutor] ✅ Executed action {action.id}: {action_type}")
            
            return ExecutionResult(
                success=True,
                status='executed',
                action_id=action.id,
                result_data=result,
                undo_available_until=undo_until
            )
            
        except Exception as e:
            logger.error(f"[ActionExecutor] ❌ Execution failed: {e}", exc_info=True)
            
            action.status = 'failed'
            action.error_message = str(e)
            await self.db.commit()
            
            return ExecutionResult(
                success=False,
                status='failed',
                action_id=action.id,
                error=str(e)
            )
    
    # ==================== Service Executors ====================
    
    async def _execute_calendar(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Create calendar event."""
        if not self.factory:
            raise RuntimeError("CredentialFactory not provided")
            
        calendar = self.factory.create_service('calendar', user_id=user_id, db_session=self.db)
        
        # Parse times
        start_time = params.get('start')
        end_time = params.get('end')
        
        # If only duration provided, calculate end time
        if not end_time and params.get('duration_minutes'):
            from datetime import datetime
            start_dt = datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time
            end_dt = start_dt + timedelta(minutes=params['duration_minutes'])
            end_time = end_dt.isoformat()
        
        result = calendar.create_event(
            summary=params.get('summary', 'Focus Time'),
            start_time=start_time,
            end_time=end_time,
            description=params.get('description', 'Auto-created by Clavr'),
            attendees=params.get('attendees', []),
            location=params.get('location'),
        )
        
        undo_data = {'event_id': result.get('id')}
        
        return {
            'event_id': result.get('id'),
            'html_link': result.get('htmlLink')
        }, undo_data
    
    async def _execute_email_draft(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Create email draft (doesn't send)."""
        if not self.factory:
            raise RuntimeError("CredentialFactory not provided")
            
        email_service = self.factory.create_service('email', user_id=user_id, db_session=self.db)
        
        result = email_service.create_draft(
            to=params.get('to', []),
            subject=params.get('subject', ''),
            body=params.get('body', ''),
            cc=params.get('cc', []),
        )
        
        undo_data = {'draft_id': result.get('id')}
        
        return {
            'draft_id': result.get('id'),
            'message': 'Draft created'
        }, undo_data
    
    async def _execute_email_send(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Send email (not undoable)."""
        if not self.factory:
            raise RuntimeError("CredentialFactory not provided")
            
        email_service = self.factory.create_service('email', user_id=user_id, db_session=self.db)
        
        result = email_service.send_email(
            to=params.get('to'),
            subject=params.get('subject', ''),
            body=params.get('body', ''),
            cc=params.get('cc', []),
            html=params.get('html', False),
        )
        
        # Email send is NOT undoable
        return {'message_id': result.get('id'), 'sent': True}, {}
    
    async def _execute_task_create(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Create task."""
        if not self.factory:
            raise RuntimeError("CredentialFactory not provided")
            
        task_service = self.factory.create_service('task', user_id=user_id, db_session=self.db)
        
        result = task_service.create_task(
            title=params.get('title') or params.get('description', 'Task'),
            notes=params.get('notes', ''),
            due_date=params.get('due_date'),
        )
        
        # Task ID and list for undo
        undo_data = {
            'task_id': result.get('id'),
            'task_list': result.get('task_list')
        }
        
        return {'task_id': result.get('id')}, undo_data
    
    async def _execute_linear_issue(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Create Linear issue."""
        # TODO: Implement Linear integration
        logger.warning("[ActionExecutor] Linear integration not yet implemented")
        return {'status': 'simulated', 'issue_id': 'MOCK-123'}, {}
    
    async def _execute_slack_message(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """Post Slack message (not undoable)."""
        if not self.factory:
            raise RuntimeError("CredentialFactory not provided")
            
        # TODO: Get Slack service and post message
        logger.warning("[ActionExecutor] Slack message not yet fully implemented")
        return {'status': 'simulated', 'ts': 'mock-ts'}, {}
    
    async def _execute_slack_status(
        self, 
        params: Dict[str, Any], 
        user_id: int
    ) -> tuple[Dict, Dict]:
        """
        Set user's Slack status (for Deep Work Shield).
        
        Params:
            status_text: Status message (e.g., "Heads-down on ENG-402")
            status_emoji: Emoji code (e.g., ":shield:" or ":computer:")
            expiration_minutes: How long until status expires (0 = no expiration)
            channel: Optional channel to post status update to
        """
        try:
            from src.integrations.slack.client import SlackClient
            import os
            
            # Initialize Slack client
            slack_client = SlackClient()
            
            status_text = params.get('status_text', 'Focusing on deep work')
            status_emoji = params.get('status_emoji', ':shield:')
            expiration_minutes = params.get('expiration_minutes', 120)  # Default 2 hours
            
            # Calculate expiration timestamp
            expiration = 0
            if expiration_minutes > 0:
                from time import time
                expiration = int(time()) + (expiration_minutes * 60)
            
            # Get user's Slack ID (in production, would look up from user profile)
            # For now, we use the authenticated user's status (their own)
            slack_user_id = params.get('slack_user_id', 'me')
            
            # Store previous status for undo
            undo_data = {
                'previous_status_text': '',
                'previous_status_emoji': '',
                'slack_user_id': slack_user_id,
            }
            
            # Set the new status
            result = slack_client.set_user_status(
                user_id=slack_user_id,
                status_text=status_text,
                status_emoji=status_emoji,
                expiration=expiration
            )
            
            # Optionally post message to a channel
            channel = params.get('channel')
            message = params.get('message')
            if channel and message:
                slack_client.post_message(channel=channel, text=message)
            
            logger.info(f"[ActionExecutor] Slack status set: {status_emoji} {status_text}")
            
            return {
                'status_set': True,
                'status_text': status_text,
                'status_emoji': status_emoji,
                'expires_in_minutes': expiration_minutes,
            }, undo_data
            
        except ImportError as e:
            logger.error(f"[ActionExecutor] Slack SDK not available: {e}")
            return {'status': 'failed', 'error': 'Slack SDK not available'}, {}
        except Exception as e:
            logger.error(f"[ActionExecutor] Slack status failed: {e}")
            raise
    

    
    async def _notify_user_after(
        self, 
        action: AutonomousAction, 
        plan: Dict[str, Any], 
        user_id: int
    ):
        """Notify user after action is executed (HIGH autonomy)."""
        await self._send_notification(
            user_id=user_id,
            action=action,
            subject=f"✅ Clavr executed: {plan.get('description', action.action_type)}",
            body=self._build_notification_body(action, plan, 'after'),
        )
    
    async def _notify_user_before(
        self, 
        action: AutonomousAction, 
        plan: Dict[str, Any], 
        user_id: int
    ):
        """Notify user before action is executed (MEDIUM autonomy)."""
        await self._send_notification(
            user_id=user_id,
            action=action,
            subject=f"🔄 Clavr is executing: {plan.get('description', action.action_type)}",
            body=self._build_notification_body(action, plan, 'before'),
        )
    
    async def _request_approval(
        self, 
        action: AutonomousAction, 
        plan: Dict[str, Any], 
        user_id: int
    ):
        """Request user approval (LOW autonomy)."""
        await self._send_notification(
            user_id=user_id,
            action=action,
            subject=f"🔔 Approval needed: {plan.get('description', action.action_type)}",
            body=self._build_notification_body(action, plan, 'approval'),
        )
    
    async def _send_notification(
        self, 
        user_id: int, 
        action: AutonomousAction, 
        subject: str, 
        body: str
    ):
        """Send notification via email, in-app, and push based on user preferences."""
        try:
            from src.services.notifications import (
                NotificationService, 
                NotificationRequest, 
                NotificationType,
                NotificationPriority,
            )
            from .autonomy_defaults import ACTION_TYPE_ICONS
            
            # Determine notification type based on action status
            if action.requires_approval and action.status == 'pending':
                notif_type = NotificationType.APPROVAL_NEEDED
                priority = NotificationPriority.HIGH
                action_label = "Review & Approve"
            elif action.status == 'executed':
                notif_type = NotificationType.ACTION_EXECUTED
                priority = NotificationPriority.NORMAL
                action_label = "View Details" if not action.is_undoable else "Undo"
            else:
                notif_type = NotificationType.SYSTEM
                priority = NotificationPriority.NORMAL
                action_label = None
            
            # Build action URL
            action_url = f"/autonomy/actions/{action.id}"
            
            # Get icon for action type
            icon = ACTION_TYPE_ICONS.get(action.action_type, 'bell')
            
            # Create notification request
            request = NotificationRequest(
                user_id=user_id,
                title=subject,
                message=body if len(body) < 500 else body[:500] + "...",
                notification_type=notif_type,
                priority=priority,
                icon=icon,
                action_url=action_url,
                action_label=action_label,
                related_action_id=action.id,
                expires_in_hours=24 if notif_type != NotificationType.APPROVAL_NEEDED else 72,
            )
            
            # Send via NotificationService (handles email + in-app + push)
            service = NotificationService(self.db)
            results = await service.send_notification(request)
            
            # Update notification tracking on action
            channels_used = [ch for ch, success in results.items() if success]
            if channels_used:
                action.notification_sent = True
                action.notification_channel = ','.join(channels_used)
                action.notification_sent_at = datetime.utcnow()
                await self.db.commit()
            
            logger.info(f"[ActionExecutor] Notifications sent via {channels_used} for action {action.id}")
            
        except Exception as e:
            logger.error(f"[ActionExecutor] Notification failed: {e}", exc_info=True)

    
    def _build_notification_body(
        self, 
        action: AutonomousAction, 
        plan: Dict[str, Any], 
        notification_type: str
    ) -> str:
        """Build HTML notification body."""
        params = plan.get('params', {})
        
        if notification_type == 'approval':
            return f"""
            <div style="font-family: sans-serif; color: #333; max-width: 600px;">
                <h2 style="color: #2563eb;">🔔 Approval Required</h2>
                <p>Clavr wants to perform the following action:</p>
                <div style="background: #f0f9ff; padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <strong>{action.action_type.replace('_', ' ').title()}</strong><br>
                    <p style="margin: 10px 0 0;">{plan.get('description', '')}</p>
                </div>
                <p>
                    <a href="#approve/{action.id}" style="background: #22c55e; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-right: 10px;">Approve</a>
                    <a href="#reject/{action.id}" style="background: #ef4444; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">Reject</a>
                </p>
            </div>
            """
        elif notification_type == 'before':
            return f"""
            <div style="font-family: sans-serif; color: #333; max-width: 600px;">
                <h2 style="color: #f59e0b;">🔄 Executing Action</h2>
                <p>Clavr is about to:</p>
                <div style="background: #fffbeb; padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <strong>{action.action_type.replace('_', ' ').title()}</strong><br>
                    <p style="margin: 10px 0 0;">{plan.get('description', '')}</p>
                </div>
            </div>
            """
        else:  # after
            undo_msg = ""
            if action.is_undoable and action.undo_expires_at:
                undo_msg = f'<p><a href="#undo/{action.id}">Undo</a> (available for {UNDO_WINDOW_MINUTES} minutes)</p>'
            
            return f"""
            <div style="font-family: sans-serif; color: #333; max-width: 600px;">
                <h2 style="color: #22c55e;">✅ Action Completed</h2>
                <p>Clavr has completed:</p>
                <div style="background: #f0fdf4; padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <strong>{action.action_type.replace('_', ' ').title()}</strong><br>
                    <p style="margin: 10px 0 0;">{plan.get('description', '')}</p>
                </div>
                {undo_msg}
            </div>
            """
    
    # ==================== Approval Methods ====================
    
    async def approve_action(self, action_id: int, user_id: int) -> ExecutionResult:
        """Approve and execute a pending action."""
        stmt = select(AutonomousAction).where(
            AutonomousAction.id == action_id,
            AutonomousAction.user_id == user_id,
            AutonomousAction.status == 'pending'
        )
        result = await self.db.execute(stmt)
        action = result.scalar_one_or_none()
        
        if not action:
            return ExecutionResult(
                success=False,
                status='not_found',
                action_id=action_id,
                error='Action not found or not pending'
            )
        
        # Execute the action
        return await self._execute_action(action, action.plan_data, user_id)
    
    async def reject_action(
        self, 
        action_id: int, 
        user_id: int, 
        reason: str = None
    ) -> bool:
        """Reject a pending action."""
        stmt = select(AutonomousAction).where(
            AutonomousAction.id == action_id,
            AutonomousAction.user_id == user_id,
            AutonomousAction.status == 'pending'
        )
        result = await self.db.execute(stmt)
        action = result.scalar_one_or_none()
        
        if not action:
            return False
        
        action.status = 'rejected'
        action.rejection_reason = reason
        await self.db.commit()
        
        logger.info(f"[ActionExecutor] Action {action_id} rejected")
        return True
    
    # ==================== Undo Methods ====================
    
    async def undo_action(self, action_id: int, user_id: int) -> bool:
        """Undo a previously executed action if within undo window."""
        stmt = select(AutonomousAction).where(
            AutonomousAction.id == action_id,
            AutonomousAction.user_id == user_id,
            AutonomousAction.status == 'executed'
        )
        result = await self.db.execute(stmt)
        action = result.scalar_one_or_none()
        
        if not action:
            logger.warning(f"[ActionExecutor] Undo failed: action {action_id} not found")
            return False
        
        if not action.is_undo_available():
            logger.warning(f"[ActionExecutor] Undo failed: window expired for action {action_id}")
            return False
        
        try:
            # Execute undo based on action type
            undo_data = action.undo_data or {}
            
            if action.action_type in ['calendar_block', 'calendar_event']:
                await self._undo_calendar(undo_data, user_id)
            elif action.action_type == 'email_draft':
                await self._undo_email_draft(undo_data, user_id)
            elif action.action_type == 'task_create':
                await self._undo_task(undo_data, user_id)
            else:
                logger.warning(f"[ActionExecutor] No undo handler for {action.action_type}")
                return False
            
            action.status = 'undone'
            action.undone_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info(f"[ActionExecutor] ✅ Action {action_id} undone")
            return True
            
        except Exception as e:
            logger.error(f"[ActionExecutor] Undo failed: {e}")
            return False
    
    async def _undo_calendar(self, undo_data: Dict, user_id: int):
        """Delete calendar event."""
        event_id = undo_data.get('event_id')
        if not event_id or not self.factory:
            return
            
        calendar = self.factory.create_service('calendar', user_id=user_id, db_session=self.db)
        calendar.delete_event(event_id)
    
    async def _undo_email_draft(self, undo_data: Dict, user_id: int):
        """Delete email draft."""
        draft_id = undo_data.get('draft_id')
        if not draft_id or not self.factory:
            return
            
        email_service = self.factory.create_service('email', user_id=user_id, db_session=self.db)
        email_service.delete_draft(draft_id)
    
    async def _undo_task(self, undo_data: Dict, user_id: int):
        """Delete task."""
        task_id = undo_data.get('task_id')
        task_list = undo_data.get('task_list')
        if not task_id or not self.factory:
            return
            
        task_service = self.factory.create_service('task', user_id=user_id, db_session=self.db)
        task_service.delete_task(task_id, task_list)
    
    # ==================== Query Methods ====================
    
    async def get_pending_actions(self, user_id: int) -> List[AutonomousAction]:
        """Get all pending actions for a user."""
        stmt = select(AutonomousAction).where(
            AutonomousAction.user_id == user_id,
            AutonomousAction.status == 'pending'
        ).order_by(AutonomousAction.created_at.desc())
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_recent_actions(
        self, 
        user_id: int, 
        limit: int = 20
    ) -> List[AutonomousAction]:
        """Get recent actions for a user."""
        stmt = select(AutonomousAction).where(
            AutonomousAction.user_id == user_id
        ).order_by(AutonomousAction.created_at.desc()).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
