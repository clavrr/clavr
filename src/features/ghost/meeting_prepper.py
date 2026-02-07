"""
Meeting Prepper Ghost

Proactively prepares for upcoming meetings by generating dossiers.
"""
from typing import Dict, Any, List
from datetime import datetime
import logging

from src.utils.logger import setup_logger
from src.database.models import User
from src.utils.config import Config

logger = setup_logger(__name__)

class MeetingPrepper:
    """
    Ghost Agent that prepares you for meetings.
    Triggered by: calendar.event.created (or starting soon)
    Action: Sends a dossier 
    """
    
    def __init__(self, db_session, config: Config):
        self.db = db_session
        self.config = config
        
    async def handle_event(self, event_type: str, payload: Dict[str, Any], user_id: int):
        """Handle calendar events"""
        if event_type not in ["calendar.event.created", "calendar.event.updated"]:
            return

        logger.info(f"[Ghost] MeetingPrepper analyzing event: {payload.get('summary')}")
        
        # 1. Filter: Is this a "High Value" meeting?
        if not self._is_high_value_meeting(payload, user_id):
            logger.info("[Ghost] Low value meeting, skipping prep.")
            return

        # 2. Generate Dossier
        dossier = await self._generate_dossier(payload, user_id)
        
        # 3. Deliver (start with Email, maybe Slack later)
        # We'll queue an email task
        from src.workers.tasks.email_tasks import send_email
        
        # Get user email
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return

        logger.info(f"[Ghost] Sending Pre-Meeting Dossier to {user.email}")
        send_email.delay(
            to=user.email,
            subject=f"📁 Dossier: {payload.get('summary')}",
            body=dossier,
            user_id=str(user_id),
            html=True
        )

    def _is_high_value_meeting(self, event: Dict[str, Any], user_id: int) -> bool:
        """
        Determine if meeting is worth prepping for.
        Criteria:
        - Has attendees (other than self)
        - User has not declined the meeting
        """
        attendees = event.get('attendees', [])
        if not attendees:
            return False
        
        # Get the user's email to identify self in attendee list
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
            
        user_email = user.email.lower()
        
        # Filter out the user from attendees to count external participants
        external_attendees = [
            a for a in attendees 
            if a.get('email', '').lower() != user_email
        ]
        
        # Meeting needs at least one external attendee to be "high value"
        if len(external_attendees) < 1:
            logger.debug(f"[Ghost] Meeting only has user, skipping.")
            return False
        
        # Check if user has declined the meeting
        for attendee in attendees:
            if attendee.get('email', '').lower() == user_email:
                response_status = attendee.get('responseStatus', '')
                if response_status == 'declined':
                    logger.debug(f"[Ghost] User declined meeting, skipping.")
                    return False
        
        return True

    async def _generate_dossier(self, event: Dict[str, Any], user_id: int) -> str:
        """Generate HTML dossier using Proactive ContextService"""
        from src.services.proactive.context_service import ProactiveContextService
        
        service = ProactiveContextService(self.config, self.db)
        
        # Build Context
        context = await service.build_meeting_context(event, user_id)
        
        # Format HTML
        title = context.get('title', 'Meeting')
        start = context.get('start_time', 'Unknown')
        attendees = context.get('attendees', [])
        documents = context.get('related_documents', [])
        topics = context.get('suggested_topics', [])
        
        # Template
        html = f"""
        <div style="font-family: sans-serif; color: #333;">
            <h2 style="color: #2563eb;">📅 Dossier: {title}</h2>
            <p><strong>Time:</strong> {start}</p>
            
            <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
            
            <h3>👥 Attendees</h3>
            <ul style="list-style: none; padding: 0;">
        """
        
        for att in attendees:
            name = att.get('name')
            history = att.get('history', [])
            last_interaction = history[0].get('date', 'Unknown') if history else "No recent history"
            
            html += f"""
                <li style="margin-bottom: 15px; background: #f8fafc; padding: 10px; border-radius: 6px;">
                    <strong>{name}</strong>
                    <div style="font-size: 0.9em; color: #64748b; margin-top: 4px;">
                        Last interaction: {last_interaction}
                    </div>
                </li>
            """
            
        html += """
            </ul>
            
            <h3>📄 Relevant Context</h3>
        """
        
        if documents:
            html += "<ul>"
            for doc in documents:
                html += f"<li><a href='{doc.get('url', '#')}'>{doc.get('title')}</a> - {doc.get('type')}</li>"
            html += "</ul>"
        else:
            html += "<p><em>No directly relevant documents found.</em></p>"
            
        if topics:
             html += f"<h3>💬 Suggested Topics</h3><p>{', '.join(topics)}</p>"
             
        html += """
            <hr>
            <p style="font-size: 0.8em; color: #94a3b8;">
                Generated by Clavr Ghost • <a href="#">Open in Dashboard</a>
            </p>
        </div>
        """
        
        return html
