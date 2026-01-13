"""
Email Action Service - Specialized logic for email actions (send, reply, labels, etc.)
"""
from typing import Optional, List, Dict, Any
from src.utils.logger import setup_logger
from .exceptions import EmailSendException, EmailNotFoundException, EmailServiceException

logger = setup_logger(__name__)

class EmailActionService:
    """
    Specialized service for email actions and modifications
    """
    
    def __init__(self, parent):
        """
        Initialize with parent EmailService
        """
        self.parent = parent
        self.config = parent.config
        self.credentials = parent.credentials
    
    @property
    def gmail_client(self):
        return self.parent.gmail_client

    def _ensure_available(self):
        self.parent._ensure_available()

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send a new email"""
        self._ensure_available()
        try:
            logger.info(f"[EMAIL_ACTION] Sending email to {to}: {subject}")
            result = self.gmail_client.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                attachments=attachments
            )
            return result
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to send email: {e}")
            raise EmailSendException(
                f"Failed to send email: {str(e)}",
                service_name="email",
                details={'to': to, 'subject': subject}
            )

    def reply_to_email(
        self,
        message_id: str,
        body: str,
        cc: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Reply to an existing email"""
        self._ensure_available()
        try:
            logger.info(f"[EMAIL_ACTION] Replying to email {message_id}")
            result = self.gmail_client.reply_to_email(
                message_id=message_id,
                body=body,
                cc=cc
            )
            return result
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to reply to email: {e}")
            raise EmailSendException(
                f"Failed to reply to email: {str(e)}",
                service_name="email",
                details={'message_id': message_id}
            )

    def get_email(self, message_id: str) -> Dict[str, Any]:
        """Get a single email by ID"""
        self._ensure_available()
        try:
            email = self.gmail_client.get_message(message_id)
            if not email:
                raise EmailNotFoundException(f"Email {message_id} not found", service_name="email")
            return email
        except EmailNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to get email: {e}")
            raise EmailServiceException(
                f"Failed to get email: {str(e)}",
                service_name="email",
                details={'message_id': message_id}
            )

    def mark_as_read(self, message_ids: List[str]):
        """Mark emails as read"""
        self._ensure_available()
        try:
            self.gmail_client.batch_modify_message_labels(
                message_ids=message_ids,
                remove_label_ids=['UNREAD']
            )
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to mark as read: {e}")
            raise EmailServiceException(f"Failed to mark as read: {e}", service_name="email")

    def mark_as_unread(self, message_ids: List[str]):
        """Mark emails as unread"""
        self._ensure_available()
        try:
            self.gmail_client.batch_modify_message_labels(
                message_ids=message_ids,
                add_label_ids=['UNREAD']
            )
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to mark as unread: {e}")
            raise EmailServiceException(f"Failed to mark as unread: {e}", service_name="email")

    def archive_emails(self, message_ids: List[str]):
        """Archive emails (remove from INBOX)"""
        self._ensure_available()
        try:
            self.gmail_client.batch_modify_message_labels(
                message_ids=message_ids,
                remove_label_ids=['INBOX']
            )
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to archive: {e}")
            raise EmailServiceException(f"Failed to archive: {e}", service_name="email")

    def delete_emails(self, message_ids: List[str]):
        """Move emails to trash"""
        self._ensure_available()
        try:
            for msg_id in message_ids:
                self.gmail_client.trash_message(msg_id)
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to delete: {e}")
            raise EmailServiceException(f"Failed to delete: {e}", service_name="email")

    def apply_label(self, message_ids: List[str], label: str):
        """Apply a label to emails"""
        self._ensure_available()
        try:
            # First ensure label exists or get ID
            label_id = self.gmail_client.get_or_create_label_id(label)
            self.gmail_client.batch_modify_message_labels(
                message_ids=message_ids,
                add_label_ids=[label_id]
            )
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to apply label: {e}")
            raise EmailServiceException(f"Failed to apply label: {e}", service_name="email")

    def remove_label(self, message_ids: List[str], label: str):
        """Remove a label from emails"""
        self._ensure_available()
        try:
            label_id = self.gmail_client.get_or_create_label_id(label)
            self.gmail_client.batch_modify_message_labels(
                message_ids=message_ids,
                remove_label_ids=[label_id]
            )
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to remove label: {e}")
            raise EmailServiceException(f"Failed to remove label: {e}", service_name="email")

    def get_inbox_stats(self) -> Dict[str, Any]:
        """Get inbox statistics"""
        self._ensure_available()
        try:
            return self.gmail_client.get_inbox_stats()
        except Exception as e:
            logger.error(f"[EMAIL_ACTION] Failed to get stats: {e}")
            return {"unread_count": 0, "total_count": 0}
