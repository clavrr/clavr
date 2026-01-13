"""
Reminder Scheduler Service.

Monitors actionable items and triggers proactive reminders based on due dates.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import ActionableItem, User
from src.database import get_db_context
from sqlalchemy import select, and_

logger = setup_logger(__name__)

class ReminderScheduler:
    """Schedules and triggers reminders for actionable items."""
    
    def __init__(self, config: Config):
        self.config = config
        
    async def check_and_send_reminders(self):
        """
        Main loop to check for due items and send notifications.
        Should be called by a periodic Celery task (e.g., hourly).
        """
        logger.info("[ReminderScheduler] Checking for pending reminders...")
        
        with get_db_context() as session:
            # Find items pending and due within warning windows
            # Logic: 
            # - Bill: 3 days before, 1 day before
            # - Deadline: 2 days before, 1 day before
            # - Appointment: 1 day before, 2 hours before (requires finer schedule)
            
            # Simplified Logic: Check items due in next 3 days that haven't been reminded recently
            now = datetime.utcnow()
            three_days_out = now + timedelta(days=3)
            
            query = select(ActionableItem).where(
                and_(
                    ActionableItem.status == 'pending',
                    ActionableItem.due_date <= three_days_out,
                    ActionableItem.due_date > now, # Not overdue yet (or handle overdue separately)
                    # Don't spam: check reminder_sent_at
                    # (ActionableItem.reminder_sent_at == None) # Simplified: send once
                )
            )
            
            results = session.execute(query).scalars().all()
            
            sent_count = 0
            for item in results:
                if self._should_remind(item):
                    await self._send_notification(item)
                    item.reminder_sent_at = datetime.utcnow()
                    item.status = 'reminded' # Or keep pending?
                    sent_count += 1
            
            if sent_count > 0:
                session.commit()
                logger.info(f"[ReminderScheduler] Sent {sent_count} reminders")

    def _should_remind(self, item: ActionableItem) -> bool:
        """Determine if we should send a reminder now."""
        # Check if already reminded today
        if item.reminder_sent_at:
            # If reminded within 24 hours, skip
            if datetime.utcnow() - item.reminder_sent_at < timedelta(hours=24):
                return False
                
        # Remind 3 days out and 1 day out
        days_until = (item.due_date - datetime.utcnow()).days
        if days_until <= 3:
            return True
        return False

    async def _send_notification(self, item: ActionableItem):
        """Trigger the actual notification (mock or Celery)."""
        # Integration point with notification_tasks
        # from src.workers.tasks.notification_tasks import send_email_notification
        
        logger.info(f"🔔 REMINDER: {item.title} due on {item.due_date}")
        # In real impl: send_alert.delay(...) or send_email_notification.delay(...)
