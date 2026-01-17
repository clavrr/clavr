"""
Document Tracker Ghost

Alerts user when important documents are updated.
Watches for changes to contracts, shared docs, and key files.
"""
from typing import Dict, Any, List
from datetime import datetime
import logging

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User

logger = setup_logger(__name__)

# Keywords that indicate important documents
IMPORTANT_DOC_KEYWORDS = [
    'contract', 'agreement', 'proposal', 'invoice', 
    'statement', 'budget', 'roadmap', 'strategy',
    'confidential', 'nda', 'terms'
]


class DocumentTrackerAgent:
    """
    Ghost Agent that tracks important document changes.
    
    Event Trigger: document.indexed (when a doc is indexed/re-indexed)
    Action: Alert user if important document was updated
    """
    
    def __init__(self, db_session, config: Config):
        self.db = db_session
        self.config = config
        
    async def handle_event(self, event_type: str, payload: Dict[str, Any], user_id: int):
        """Handle document indexed events."""
        if event_type != "document.indexed":
            return
        
        doc_title = payload.get('title', '').lower()
        doc_type = payload.get('type', '')
        doc_id = payload.get('id')
        
        logger.info(f"[Ghost] DocTracker analyzing: {doc_title}")
        
        # Check if important
        importance = self._check_importance(payload)
        
        if not importance:
            logger.debug(f"[DocTracker] Document not important: {doc_title}")
            return
        
        # Check if this is an update (not first index)
        is_update = payload.get('is_update', False)
        
        if is_update:
            await self._send_update_alert(user_id, payload, importance)
        else:
            # First time seeing this doc, just log
            logger.info(f"[DocTracker] Tracking new important doc: {doc_title}")

    def _check_importance(self, doc: Dict[str, Any]) -> str:
        """
        Check if document is important.
        Returns reason string or empty.
        """
        title = doc.get('title', '').lower()
        content_preview = doc.get('content', '')[:500].lower() if doc.get('content') else ''
        
        # Check title for keywords
        for keyword in IMPORTANT_DOC_KEYWORDS:
            if keyword in title:
                return f'title_contains_{keyword}'
        
        # Check content for keywords
        for keyword in IMPORTANT_DOC_KEYWORDS:
            if keyword in content_preview:
                return f'content_contains_{keyword}'
        
        # Check if shared by many
        if doc.get('shared_count', 0) > 5:
            return 'widely_shared'
        
        # Check if recently created by important person
        # This would require graph lookup...
        
        return ''

    async def _send_update_alert(self, user_id: int, doc: Dict[str, Any], importance: str):
        """Send alert about document update."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        
        html = self._build_alert_email(doc, importance)
        
        from src.workers.tasks.email_tasks import send_email
        
        logger.info(f"[Ghost] Sending doc update alert to {user.email}")
        send_email.delay(
            to=user.email,
            subject=f"📄 Document Updated: {doc.get('title', 'Untitled')}",
            body=html,
            user_id=str(user_id),
            html=True
        )

    def _build_alert_email(self, doc: Dict[str, Any], importance: str) -> str:
        """Build HTML email for document alert."""
        title = doc.get('title', 'Untitled')
        updated_by = doc.get('last_modified_by', 'Someone')
        updated_at = doc.get('last_modified', datetime.utcnow().isoformat())
        doc_url = doc.get('url', '#')
        
        html = f"""
        <div style="font-family: sans-serif; color: #333; max-width: 600px;">
            <h2 style="color: #f59e0b;">📄 Document Update Alert</h2>
            
            <div style="background: #fffbeb; padding: 20px; border-radius: 8px; border-left: 4px solid #f59e0b; margin: 20px 0;">
                <h3 style="margin: 0 0 10px 0;">{title}</h3>
                <p style="color: #64748b; margin: 5px 0;">
                    <strong>Updated by:</strong> {updated_by}
                </p>
                <p style="color: #64748b; margin: 5px 0;">
                    <strong>When:</strong> {updated_at}
                </p>
                <p style="color: #64748b; margin: 5px 0;">
                    <strong>Why tracked:</strong> {importance.replace('_', ' ')}
                </p>
            </div>
            
            <p style="text-align: center;">
                <a href="{doc_url}" style="background: #f59e0b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">
                    View Document
                </a>
            </p>
            
            <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
            <p style="font-size: 0.8em; color: #94a3b8; text-align: center;">
                Generated by Clavr Ghost • <a href="#">Manage tracked documents</a>
            </p>
        </div>
        """
        
        return html
