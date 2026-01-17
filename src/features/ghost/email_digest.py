"""
Email Digest Ghost

Sends daily morning digest of important/unread emails.
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import logging

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User

logger = setup_logger(__name__)


class EmailDigestAgent:
    """
    Ghost Agent that sends daily email digests.
    
    Scheduled Trigger: Daily (morning, e.g., 7 AM user local time)
    Action: Summarize important unread emails and send digest
    """
    
    def __init__(self, db_session, config: Config):
        self.db = db_session
        self.config = config
        
    async def generate_digest(self, user_id: int) -> Dict[str, Any]:
        """
        Generate email digest for a user.
        Returns summary of important unread emails from last 24 hours.
        """
        digest = {
            'user_id': user_id,
            'generated_at': datetime.utcnow().isoformat(),
            'important_emails': [],
            'unread_count': 0,
            'summary': ''
        }
        
        try:
            from src.core.async_credential_provider import AsyncCredentialFactory
            
            # Get user
            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                return digest
            
            factory = AsyncCredentialFactory(self.config, self.db, user)
            email_service = await factory.get_email_service()
            
            if not email_service:
                logger.warning(f"[Digest] No email service for user {user_id}")
                return digest
            
            # Get unread emails from last 24 hours
            yesterday = datetime.utcnow() - timedelta(days=1)
            
            emails = await email_service.search_emails(
                query="is:unread",
                max_results=50
            )
            
            # Filter and prioritize
            important = []
            for email in emails or []:
                # Check if important (starred, from known contact, etc.)
                is_important = self._is_important_email(email)
                if is_important:
                    important.append({
                        'id': email.get('id'),
                        'subject': email.get('subject', 'No subject'),
                        'from': email.get('from', 'Unknown'),
                        'snippet': email.get('snippet', '')[:150],
                        'received_at': email.get('internalDate'),
                        'importance_reason': is_important
                    })
            
            digest['important_emails'] = important[:10]
            digest['unread_count'] = len(emails or [])
            digest['summary'] = f"{len(important)} important emails out of {len(emails or [])} unread"
            
            logger.info(f"[Digest] Generated for user {user_id}: {digest['summary']}")
            
        except Exception as e:
            logger.error(f"[Digest] Generation failed: {e}")
            
        return digest

    def _is_important_email(self, email: Dict[str, Any]) -> str:
        """
        Determine if email is important and why.
        Returns reason string or empty if not important.
        """
        labels = email.get('labelIds', [])
        subject = email.get('subject', '').lower()
        sender = email.get('from', '').lower()
        
        # Check for importance signals
        if 'STARRED' in labels:
            return 'starred'
        if 'IMPORTANT' in labels:
            return 'gmail_important'
        if any(word in subject for word in ['urgent', 'asap', 'action required', 'deadline']):
            return 'urgent_keywords'
        if any(word in subject for word in ['invoice', 'payment', 'contract']):
            return 'financial'
        if 'calendar-notification' in sender or 'meet' in sender:
            return 'meeting_related'
            
        return ''

    async def send_digest(self, user_id: int):
        """
        Generate and send the email digest.
        Called by scheduled task.
        """
        digest = await self.generate_digest(user_id)
        
        if not digest['important_emails']:
            logger.info(f"[Digest] No important emails for user {user_id}, skipping")
            return
        
        # Get user
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        
        # Build HTML
        html = self._build_digest_email(digest)
        
        # Queue email
        from src.workers.tasks.email_tasks import send_email
        
        logger.info(f"[Ghost] Sending email digest to {user.email}")
        send_email.delay(
            to=user.email,
            subject=f"📬 Morning Digest: {digest['summary']}",
            body=html,
            user_id=str(user_id),
            html=True
        )

    def _build_digest_email(self, digest: Dict[str, Any]) -> str:
        """Build HTML email for digest."""
        html = f"""
        <div style="font-family: sans-serif; color: #333; max-width: 600px;">
            <h2 style="color: #2563eb;">📬 Your Morning Digest</h2>
            <p style="color: #64748b;">{digest['summary']}</p>
            
            <div style="margin: 20px 0;">
        """
        
        for email in digest['important_emails']:
            reason = email.get('importance_reason', '')
            reason_badge = f'<span style="background: #dbeafe; color: #1e40af; padding: 2px 6px; border-radius: 4px; font-size: 0.75em;">{reason}</span>' if reason else ''
            
            html += f"""
                <div style="background: #f8fafc; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #2563eb;">
                    <div style="display: flex; justify-content: space-between; align-items: start;">
                        <strong>{email.get('subject', 'No subject')}</strong>
                        {reason_badge}
                    </div>
                    <div style="font-size: 0.85em; color: #64748b; margin-top: 5px;">
                        From: {email.get('from', 'Unknown')}
                    </div>
                    <div style="font-size: 0.9em; color: #475569; margin-top: 8px;">
                        {email.get('snippet', '')}
                    </div>
                </div>
            """
        
        html += f"""
            </div>
            <p style="text-align: center;">
                <a href="#" style="background: #2563eb; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">
                    Open Inbox
                </a>
            </p>
            <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
            <p style="font-size: 0.8em; color: #94a3b8; text-align: center;">
                Generated by Clavr Ghost • {digest['unread_count']} total unread
            </p>
        </div>
        """
        
        return html
