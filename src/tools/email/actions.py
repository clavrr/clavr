"""
Email Actions Module

Handles email actions: send, reply, mark read/unread, delete, archive, organize, etc.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import re

from ...utils.logger import setup_logger
from ..constants import ToolLimits
from ...integrations.gmail.service import EmailService

logger = setup_logger(__name__)


class EmailActions:
    """Email action operations (send, reply, mark, delete, archive, organize)"""
    
    def __init__(self, email_service: EmailService, date_parser: Optional[Any] = None):
        """
        Initialize email actions
        
        Args:
            email_service: Email service instance
            date_parser: Optional date parser for flexible date handling
        """
        self.email_service = email_service
        # Keep backward compatibility
        self.google_client = email_service.gmail_client if hasattr(email_service, 'gmail_client') else None
        self.date_parser = date_parser
    
    def send_email(self, to: str, subject: str, body: str, schedule_time: Optional[str] = None) -> str:
        """Send email via Gmail (with optional scheduling)"""
        try:
            if not to or not subject or not body:
                return "[ERROR] To, subject, and body are required to send an email"
            
            # Parse schedule time if provided
            parsed_schedule_time = None
            if schedule_time:
                parsed_schedule_time = self._parse_schedule_time(schedule_time)
                if not parsed_schedule_time:
                    return f"[ERROR] Could not parse schedule time: {schedule_time}"
            
            sent_message = self.google_client.send_message(
                to=to,
                subject=subject,
                body=body,
                schedule_time=parsed_schedule_time
            )
            
            if sent_message:
                message_id = sent_message.get('id', 'Unknown')
                if parsed_schedule_time:
                    return f"[OK] Email scheduled to {to} at {parsed_schedule_time}\nMessage ID: {message_id}"
                else:
                    return f"[OK] Email sent to {to}\nSubject: {subject}\nMessage ID: {message_id}"
            else:
                return f"[ERROR] Failed to send email to {to}"
            
        except Exception as e:
            raise Exception(f"Failed to send Gmail: {str(e)}")
    
    def reply_to_email(self, message_id: str, body: str) -> str:
        """Reply to an email via Gmail"""
        try:
            if not message_id or not body:
                return "[ERROR] Message ID and body are required to reply to an email"
            
            original_message = self.google_client.get_message(message_id)
            if not original_message:
                return f"[ERROR] Could not find message with ID: {message_id}"
            
            sender = original_message.get('sender', '')
            original_subject = original_message.get('subject', '')
            reply_subject = f"Re: {original_subject}" if not original_subject.startswith('Re:') else original_subject
            
            sent_message = self.google_client.send_message(
                to=sender,
                subject=reply_subject,
                body=body
            )
            
            if sent_message:
                return f"[OK] Replied to email from {sender}\nSubject: {reply_subject}\nReply: {body[:ToolLimits.MAX_BODY_PREVIEW_LENGTH]}..."
            else:
                return f"[ERROR] Failed to reply to email from {sender}"
            
        except Exception as e:
            raise Exception(f"Failed to reply to Gmail: {str(e)}")
    
    def mark_as_read(self, message_id: str) -> str:
        """Mark email as read in Gmail"""
        try:
            if not message_id:
                return "[ERROR] Message ID is required to mark email as read"
            
            success = self.google_client.mark_as_read(message_id)
            
            if success:
                return f"[OK] Marked email {message_id} as read"
            else:
                return f"[ERROR] Failed to mark email {message_id} as read"
            
        except Exception as e:
            raise Exception(f"Failed to mark Gmail as read: {str(e)}")
    
    def mark_as_unread(self, message_id: str) -> str:
        """Mark email as unread in Gmail"""
        try:
            if not message_id:
                return "[ERROR] Message ID is required to mark email as unread"
            
            success = self.google_client.mark_as_unread(message_id)
            
            if success:
                return f"[OK] Marked email {message_id} as unread"
            else:
                return f"[ERROR] Failed to mark email {message_id} as unread"
            
        except Exception as e:
            raise Exception(f"Failed to mark Gmail as unread: {str(e)}")
    
    def delete_email(self, email: Dict[str, Any]) -> bool:
        """Delete email using Gmail API"""
        try:
            message_id = email.get('id')
            if not message_id:
                logger.error("No message ID provided for deletion")
                return False
            
            if not self.google_client or not self.google_client.is_available():
                logger.error("Gmail client not available")
                return False
            
            try:
                self.google_client.delete_message(message_id)
                return True
            except Exception as e:
                logger.error(f"Failed to delete email {message_id}: {e}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete email: {e}")
            return False
    
    def archive_email(self, email: Dict[str, Any]) -> bool:
        """Archive email using Gmail API"""
        try:
            message_id = email.get('id')
            if not message_id:
                logger.error("No message ID provided for archiving")
                return False
            
            if not self.google_client or not self.google_client.is_available():
                logger.error("Gmail client not available")
                return False
            
            try:
                self.google_client.archive_message(message_id)
                return True
            except Exception as e:
                logger.error(f"Failed to archive email {message_id}: {e}")
                return False
        except Exception as e:
            logger.error(f"Failed to archive email: {e}")
            return False
    
    def move_to_category(self, email: Dict[str, Any], category: str) -> bool:
        """Move email to category-specific folder/label"""
        try:
            # For now, archiving serves as moving to a category
            return self.archive_email(email)
        except Exception as e:
            logger.error(f"Failed to move email to category: {e}")
            return False
    
    def apply_category(self, email: Dict[str, Any], category: str) -> bool:
        """Apply category label to email"""
        try:
            message_id = email.get('id')
            if not message_id:
                logger.error("No message ID provided")
                return False
            
            if not self.google_client or not self.google_client.is_available():
                logger.error("Gmail client not available")
                return False
            
            logger.info(f"Would apply category {category} to email {message_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply category: {e}")
            return False
    
    def _parse_schedule_time(self, schedule_time_str: str) -> Optional[datetime]:
        """
        Parse natural language schedule time to datetime
        
        Supports formats like:
        - "2pm", "3 pm", "10am", "2:30 PM"  (today)
        - "tomorrow at 3pm"
        - "next Monday at 2pm"
        - "in 2 hours"
        - "2024-12-25T15:30:00" (ISO format)
        - "2024-12-25 15:30:00"
        """
        try:
            schedule_time_str = schedule_time_str.strip()
            schedule_time_str_lower = schedule_time_str.lower()
            
            # Try ISO format first
            try:
                if 'T' in schedule_time_str or (' ' in schedule_time_str and re.match(r'\d{4}-\d{2}-\d{2}', schedule_time_str)):
                    return datetime.fromisoformat(schedule_time_str.replace('T', ' '))
            except (ValueError, AttributeError):
                pass
            
            # Try using date parser if available
            if self.date_parser:
                try:
                    return self.date_parser.parse(schedule_time_str)
                except Exception:
                    pass
            
            # Natural language parsing
            now = datetime.now()
            
            # "in X hours/minutes/days"
            if schedule_time_str_lower.startswith('in '):
                time_str = schedule_time_str_lower[3:].strip()
                match = re.match(r'(\d+)\s*(hour|hours|minute|minutes|day|days|week|weeks)', time_str)
                if match:
                    num, unit = match.groups()
                    num = int(num)
                    if 'hour' in unit:
                        return now + timedelta(hours=num)
                    elif 'minute' in unit:
                        return now + timedelta(minutes=num)
                    elif 'day' in unit:
                        return now + timedelta(days=num)
                    elif 'week' in unit:
                        return now + timedelta(weeks=num)
            
            # Parse time patterns - handle "2pm", "10am", "2:30 PM", "3 pm"
            time_patterns = [
                r'(\d{1,2}):(\d{2})\s*(am|pm)',  # "2:30 pm" or "2:30pm"
                r'(\d{1,2})(am|pm)',              # "10am" or "3pm" (no space)
                r'(\d{1,2})\s+(am|pm)',           # "3 pm" or "10 am" (with space)
            ]
            
            hour = None
            minute = 0
            am_pm = None
            
            for pattern in time_patterns:
                match = re.search(pattern, schedule_time_str_lower)
                if match:
                    groups = match.groups()
                    hour = int(groups[0])
                    
                    # Check if we have minutes (3 groups) or just hour + am/pm (2 groups)
                    if len(groups) >= 3 and groups[1] and groups[1].isdigit():
                        # Pattern: "2:30 pm"
                        minute = int(groups[1])
                        am_pm = groups[2]
                    elif len(groups) >= 2:
                        # Pattern: "2pm" or "2 pm"
                        am_pm = groups[1]
                        minute = 0
                    
                    break
            
            # Convert to 24-hour format if we found a time
            if hour is not None and am_pm:
                if am_pm == 'pm' and hour != 12:
                    hour += 12
                elif am_pm == 'am' and hour == 12:
                    hour = 0
            
            # Determine the date
            target_date = now
            
            # "tomorrow at X" or just "tomorrow"
            if 'tomorrow' in schedule_time_str_lower:
                target_date = now + timedelta(days=1)
            # "today at X" or just plain time like "2pm"
            elif 'today' in schedule_time_str_lower or hour is not None:
                target_date = now
            # "next Monday/Tuesday/etc"
            else:
                weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                for i, day in enumerate(weekdays):
                    if day in schedule_time_str_lower:
                        days_ahead = (i - now.weekday()) % 7
                        if days_ahead == 0:  # If today, schedule for next week
                            days_ahead = 7
                        target_date = now + timedelta(days=days_ahead)
                        break
            
            # Apply the parsed time
            if hour is not None:
                result = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                logger.info(f"Parsed schedule time '{schedule_time_str}' -> {result.isoformat()}")
                return result
            
            # If no specific time was parsed, check for date-only patterns
            if 'tomorrow' in schedule_time_str_lower:
                return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            
            # Default: if we can't parse, return None
            logger.warning(f"Could not parse schedule time: '{schedule_time_str}'")
            return None
            
        except Exception as e:
            logger.warning(f"Failed to parse schedule time '{schedule_time_str}': {e}")
            return None
