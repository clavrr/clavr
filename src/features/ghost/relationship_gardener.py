"""
Relationship Gardener Ghost

Proactively monitors and nurtures professional relationships.
Features:
- Track interaction strength across email, Slack, and Calendar
- Weighted strength updates (meeting > email > Slack)
- Detect relationship decay (>30 days no contact)
- Suggest reconnections
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import logging

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User

logger = setup_logger(__name__)

# Decay threshold in days
DECAY_THRESHOLD_DAYS = 30
STRONG_RELATIONSHIP_THRESHOLD = 0.6

# Interaction source weights — meetings count more than emails,
# which count more than Slack messages.
SOURCE_WEIGHTS: Dict[str, float] = {
    "meeting": 0.20,
    "email": 0.10,
    "slack": 0.05,
}


class RelationshipGardener:
    """
    Ghost Agent that gardens your network.
    
    Event Triggers:
    - email.sent: Updates relationship strength (weight: 0.10)
    - slack.message.created: Updates from Slack interactions (weight: 0.05)
    - calendar.event.ended: Updates from meeting co-attendance (weight: 0.20)
    
    Scheduled Triggers:
    - Weekly: Analyze decay and send suggestions
    """
    
    def __init__(self, db_session, config: Config):
        self.db = db_session
        self.config = config
        
    async def handle_event(self, event_type: str, payload: Dict[str, Any], user_id: int):
        """Handle email, Slack, and Calendar events to update relationship graph."""
        if event_type == "email.sent":
            recipient = payload.get('to')
            if recipient:
                logger.info(f"[Ghost] Gardener observing email interaction with: {recipient}")
                await self._update_graph_strength_with_source(
                    user_id, recipient, source="email"
                )

        elif event_type == "slack.message.created":
            # Extract recipient from Slack DMs or @mentions
            recipients = self._extract_slack_recipients(payload)
            for recipient in recipients:
                logger.info(f"[Ghost] Gardener observing Slack interaction with: {recipient}")
                await self._update_graph_strength_with_source(
                    user_id, recipient, source="slack"
                )

        elif event_type in ("calendar.event.ended", "calendar.event.completed"):
            # Extract all external attendees from the meeting
            attendees = self._extract_meeting_attendees(payload, user_id)
            for attendee_email in attendees:
                logger.info(f"[Ghost] Gardener observing meeting with: {attendee_email}")
                await self._update_graph_strength_with_source(
                    user_id, attendee_email, source="meeting"
                )
        else:
            return

    def _extract_slack_recipients(self, payload: Dict[str, Any]) -> List[str]:
        """Extract email addresses from Slack message interactions."""
        recipients = []
        # Direct messages
        if payload.get("channel_type") == "im":
            user_email = payload.get("user_email")
            if user_email:
                recipients.append(user_email)
        # @mentions in channels
        mentions = payload.get("mentioned_users", [])
        for mention in mentions:
            email = mention.get("email")
            if email:
                recipients.append(email)
        return recipients

    def _extract_meeting_attendees(
        self, payload: Dict[str, Any], user_id: int
    ) -> List[str]:
        """Extract external attendee emails from a calendar event."""
        attendees = payload.get("attendees", [])
        user_email = payload.get("organizer_email", "")
        external = []
        for att in attendees:
            email = att.get("email", "")
            if email and email != user_email and not att.get("self", False):
                external.append(email)
        return external

    async def _update_graph_strength_with_source(
        self, user_id: int, recipient: str, source: str = "email"
    ):
        """
        Update the COMMUNICATES_WITH edge in the graph with source-weighted
        strength increments.

        Source weights:
        - meeting: +0.20 per interaction
        - email: +0.10 per interaction
        - slack: +0.05 per interaction
        """
        weight = SOURCE_WEIGHTS.get(source, 0.10)

        try:
            from src.services.indexing.graph import KnowledgeGraphManager
            from src.services.indexing.graph.schema import NodeType
            
            kg = KnowledgeGraphManager(self.config)
            
            # AQL upsert for relationship tracking with source-weighted strength
            query = """
            // Ensure User node reference
            LET user_key = CONCAT("user:", @user_id)
            
            // Upsert Person node
            UPSERT { email: @email }
            INSERT { 
                email: @email, 
                name: SPLIT(@email, "@")[0],
                created_at: DATE_ISO8601(DATE_NOW()),
                node_type: "Person"
            }
            UPDATE {} 
            IN Person
            OPTIONS { waitForSync: true }
            
            LET person = NEW
            
            // Upsert COMMUNICATES_WITH edge with source-weighted strength
            UPSERT { _from: CONCAT("User/", @user_id), _to: person._id }
            INSERT { 
                _from: CONCAT("User/", @user_id), 
                _to: person._id,
                last_interaction: DATE_ISO8601(DATE_NOW()),
                interaction_count: 1,
                strength: @weight,
                first_seen: DATE_ISO8601(DATE_NOW()),
                rel_type: "COMMUNICATES_WITH",
                email_count: @source == "email" ? 1 : 0,
                slack_count: @source == "slack" ? 1 : 0,
                meeting_count: @source == "meeting" ? 1 : 0,
                last_source: @source
            }
            UPDATE { 
                last_interaction: DATE_ISO8601(DATE_NOW()),
                interaction_count: OLD.interaction_count + 1,
                strength: MIN(1.0, OLD.strength + @weight),
                email_count: @source == "email" ? (OLD.email_count || 0) + 1 : (OLD.email_count || 0),
                slack_count: @source == "slack" ? (OLD.slack_count || 0) + 1 : (OLD.slack_count || 0),
                meeting_count: @source == "meeting" ? (OLD.meeting_count || 0) + 1 : (OLD.meeting_count || 0),
                last_source: @source
            }
            IN COMMUNICATES_WITH
            OPTIONS { waitForSync: true }
            
            RETURN NEW.strength
            """
            
            result = await kg.execute_query(query, {
                'user_id': str(user_id),
                'email': recipient.lower(),
                'weight': weight,
                'source': source,
            })
            
            if result:
                logger.debug(
                    f"[Gardener] Edge strength ({source}): "
                    f"{result[0] if result else 'N/A'}"
                )
                
        except Exception as e:
            logger.error(f"[Gardener] Graph update failed: {e}")

    async def analyze_decay(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Find relationships that are decaying (no interaction > threshold).
        Now considers all interaction sources (email, Slack, calendar).
        """
        decaying = []
        
        try:
            from src.services.indexing.graph import KnowledgeGraphManager
            
            kg = KnowledgeGraphManager(self.config)
            
            # Calculate the cutoff date for decay
            cutoff_date = (datetime.utcnow() - timedelta(days=DECAY_THRESHOLD_DAYS)).isoformat()
            
            # AQL query to find decaying strong relationships with multi-source info
            query = """
            FOR edge IN COMMUNICATES_WITH
                FILTER edge._from == CONCAT("User/", @user_id)
                FILTER edge.strength >= @strength_threshold
                FILTER edge.last_interaction < @cutoff_date
                
                LET person = DOCUMENT(edge._to)
                
                FILTER person != null
                
                SORT edge.strength DESC
                LIMIT 10
                
                RETURN {
                    email: person.email,
                    name: person.name != null ? person.name : SPLIT(person.email, "@")[0],
                    strength: edge.strength,
                    last_interaction: edge.last_interaction,
                    total_interactions: edge.interaction_count,
                    email_count: edge.email_count || 0,
                    slack_count: edge.slack_count || 0,
                    meeting_count: edge.meeting_count || 0,
                    last_source: edge.last_source || "email"
                }
            """
            
            result = await kg.execute_query(query, {
                'user_id': str(user_id),
                'strength_threshold': STRONG_RELATIONSHIP_THRESHOLD,
                'cutoff_date': cutoff_date
            })
            
            for row in result or []:
                # Parse last_interaction if it's a string
                last_interaction = row.get('last_interaction')
                if isinstance(last_interaction, str):
                    try:
                        last_dt = datetime.fromisoformat(last_interaction.replace('Z', '+00:00'))
                        days_since = (datetime.utcnow() - last_dt.replace(tzinfo=None)).days
                    except (ValueError, TypeError):
                        days_since = DECAY_THRESHOLD_DAYS
                else:
                    days_since = DECAY_THRESHOLD_DAYS
                    
                decaying.append({
                    'email': row.get('email'),
                    'name': row.get('name', row.get('email', '').split('@')[0] if row.get('email') else 'Unknown'),
                    'strength': row.get('strength', 0),
                    'days_since_contact': days_since,
                    'total_interactions': row.get('total_interactions', 0),
                    'email_count': row.get('email_count', 0),
                    'slack_count': row.get('slack_count', 0),
                    'meeting_count': row.get('meeting_count', 0),
                    'last_source': row.get('last_source', 'email'),
                })
                
            logger.info(f"[Gardener] Found {len(decaying)} decaying relationships for user {user_id}")
            
        except Exception as e:
            logger.error(f"[Gardener] Decay analysis failed: {e}")
            
        return decaying

    async def send_reconnect_suggestions(self, user_id: int):
        """
        Analyze decay and send email with reconnect suggestions.
        Called by scheduled task.
        """
        decaying = await self.analyze_decay(user_id)
        
        if not decaying:
            logger.info(f"[Gardener] No decaying relationships for user {user_id}")
            return
        
        # Get user email
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        
        # Build HTML email
        html = self._build_reconnect_email(decaying)
        
        # Queue email
        from src.workers.tasks.email_tasks import send_email
        
        logger.info(f"[Ghost] Sending reconnect suggestions to {user.email}")
        send_email.delay(
            to=user.email,
            subject="🌱 Relationship Check-In",
            body=html,
            user_id=str(user_id),
            html=True
        )

    def _build_reconnect_email(self, decaying: List[Dict]) -> str:
        """Build HTML email for reconnect suggestions with multi-source context."""
        html = """
        <div style="font-family: sans-serif; color: #333; max-width: 600px;">
            <h2 style="color: #16a34a;">🌱 Time to Reconnect</h2>
            <p>Clavr noticed some important relationships that could use some attention:</p>
            
            <div style="margin: 20px 0;">
        """
        
        for person in decaying[:5]:
            name = person.get('name', 'Someone')
            days = person.get('days_since_contact', 0)
            # Show interaction breakdown
            sources = []
            if person.get('email_count', 0):
                sources.append(f"{person['email_count']} emails")
            if person.get('slack_count', 0):
                sources.append(f"{person['slack_count']} Slack msgs")
            if person.get('meeting_count', 0):
                sources.append(f"{person['meeting_count']} meetings")
            source_text = " · ".join(sources) if sources else "via email"
            
            html += f"""
                <div style="background: #f0fdf4; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #16a34a;">
                    <strong>{name}</strong>
                    <div style="font-size: 0.9em; color: #64748b; margin-top: 5px;">
                        Last contact: {days} days ago · {source_text}
                    </div>
                </div>
            """
        
        html += """
            </div>
            <p style="font-size: 0.85em; color: #94a3b8;">
                A quick message can go a long way in maintaining professional relationships.
            </p>
            <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
            <p style="font-size: 0.8em; color: #94a3b8;">
                Generated by Clavr Ghost • <a href="#">Manage preferences</a>
            </p>
        </div>
        """
        
        return html


