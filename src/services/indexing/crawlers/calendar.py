"""
Calendar Crawler

Background indexer that crawls Google Calendar events for the knowledge graph.
Creates CalendarEvent nodes, links to attendees, and creates temporal relationships.

Features:
- Indexes Calendar events
- Creates Person nodes for attendees
- Links to TimeBlocks for temporal queries
- Detects scheduling conflicts (OVERLAPS relationships)
- Extracts topics from event descriptions
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio
from google.auth.exceptions import RefreshError
from src.core.base.exceptions import AuthenticationExpiredError
from src.database.models import ActionableItem
from src.database import get_db_context

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode, Relationship
from src.services.indexing.graph.schema import NodeType, RelationType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class CalendarCrawler(BaseIndexer):
    """
    Crawler that periodically indexes Google Calendar events.
    
    Processes:
    - Calendar events (past and future)
    - Event attendees → Person nodes
    - Scheduling conflicts → OVERLAPS relationships
    """
    
    def __init__(
        self,
        config,
        user_id: int,
        calendar_service=None,
        **kwargs
    ):
        """
        Initialize Calendar crawler.
        
        Args:
            config: Application configuration
            user_id: User ID to index for
            calendar_service: CalendarService instance
        """
        super().__init__(config, user_id, **kwargs)
        self.calendar_service = calendar_service
        self.last_sync_time = datetime.now() - timedelta(days=7)
        self._event_cache = {}  # Cache event IDs to detect updates
        
        # Calendar-specific settings from ServiceConstants
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.CALENDAR_SYNC_INTERVAL
        self.days_back = ServiceConstants.CALENDAR_DAYS_BACK
        self.days_ahead = ServiceConstants.CALENDAR_DAYS_AHEAD
    
    @property
    def name(self) -> str:
        return "calendar"
    
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch calendar events that are upcoming or recently modified.
        """
        if not self.calendar_service:
            logger.warning("[CalendarCrawler] No Calendar service available, skipping sync")
            return []
        
        new_items = []
        
        try:
            # Fetch events from the service
            events = await asyncio.to_thread(
                self.calendar_service.list_events,
                start_date=None,  # Will use days_back
                end_date=None,    # Will use days_ahead
                days_back=self.days_back,
                days_ahead=self.days_ahead,
                max_results=200
            )
            
            logger.debug(f"[CalendarCrawler] Found {len(events)} events in range")
            
            for event in events:
                event_id = event.get('id')
                updated = event.get('updated')
                
                # Check if this is a new or updated event
                if event_id in self._event_cache:
                    if self._event_cache[event_id] == updated:
                        continue  # Skip unchanged events
                
                self._event_cache[event_id] = updated
                new_items.append(event)
            
            logger.info(f"[CalendarCrawler] {len(new_items)} new/updated events to index")
            return new_items
            
        except (AuthenticationExpiredError, RefreshError) as e:
            logger.critical(f"[CalendarCrawler] Authentication expired/revoked: {e}")
            
            # Create system alert for user
            try:
                alert_id = f"auth_alert_{self.user_id}_google"
                with get_db_context() as db_session:
                    alert = ActionableItem(
                        id=alert_id,
                        user_id=self.user_id,
                        title="Reconnect Google Account",
                        item_type="system_alert",
                        due_date=datetime.utcnow(),
                        urgency="high",
                        source_type="system",
                        source_id="auth_monitor",
                        suggested_action="Re-authenticate",
                        status="pending"
                    )
                    db_session.merge(alert)
                    db_session.commit()
                    logger.info(f"[CalendarCrawler] Created re-auth alert: {alert_id}")
            except Exception as alert_err:
                logger.error(f"[CalendarCrawler] Failed to create auth alert: {alert_err}")
                
            return []
        except Exception as e:
            if "invalid_grant" in str(e).lower():
                logger.critical(f"[CalendarCrawler] Auth error (invalid_grant): {e}")
                # Treat invalid_grant as AuthenticationExpiredError
                try:
                    alert_id = f"auth_alert_{self.user_id}_google"
                    with get_db_context() as db_session:
                        # Check if alert already exists to avoid spamming
                        # (merge handles upsert, but we want to ensure it's open)
                        alert = ActionableItem(
                            id=alert_id,
                            user_id=self.user_id,
                            title="Reconnect Google Account",
                            item_type="system_alert",
                            due_date=datetime.utcnow(),
                            urgency="high",
                            source_type="system",
                            source_id="auth_monitor",
                            suggested_action="Re-authenticate",
                            status="pending"
                        )
                        db_session.merge(alert)
                        db_session.commit()
                        logger.info(f"[CalendarCrawler] Created re-auth alert for invalid_grant: {alert_id}")
                except Exception as alert_err:
                    logger.error(f"[CalendarCrawler] Failed to create auth alert: {alert_err}")
                return []
            
            logger.error(f"[CalendarCrawler] Fetch delta failed: {e}")
            return []
    
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform a Google Calendar event into graph nodes.
        """
        try:
            nodes = []
            
            event_id = item.get('id')
            if not event_id:
                return None
            
            # Extract event properties
            summary = item.get('summary', 'Untitled Event')
            description = item.get('description', '')
            location = item.get('location')
            
            # Parse start/end times
            start_data = item.get('start', {})
            end_data = item.get('end', {})
            
            start_time = start_data.get('dateTime') or start_data.get('date')
            end_time = end_data.get('dateTime') or end_data.get('date')
            
            # Get attendees
            attendees = item.get('attendees', [])
            organizer = item.get('organizer', {})
            
            # Build searchable text
            searchable_parts = [summary]
            if description:
                searchable_parts.append(description)
            if location:
                searchable_parts.append(f"Location: {location}")
            for attendee in attendees[:5]:  # Include up to 5 attendees
                attendee_name = attendee.get('displayName') or attendee.get('email', '')
                searchable_parts.append(attendee_name)
            
            searchable_text = ' '.join(searchable_parts)
            
            # Create CalendarEvent node
            node_id = f"calendar_event_{event_id.replace('-', '_').replace('@', '_')}"
            
            event_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.CALENDAR_EVENT,
                properties={
                    'title': summary,
                    'description': description[:2000] if description else '',
                    'location': location,
                    'start_time': start_time,
                    'end_time': end_time,
                    'google_event_id': event_id,
                    'source': 'google_calendar',
                    'user_id': self.user_id,
                    'timestamp': start_time,  # For temporal indexing
                    'attendee_count': len(attendees),
                    'status': item.get('status'),
                    'html_link': item.get('htmlLink'),
                },
                searchable_text=searchable_text[:10000],
                relationships=[]
            )
            
            # FIXED: Link to User for graph connectivity
            # CalendarEvent BELONGS_TO User - ensures events appear in visualization
            event_node.relationships.append({
                'from_node': node_id,
                'to_node': f"User/{self.user_id}",
                'rel_type': RelationType.BELONGS_TO.value,
                'properties': {'source': 'google_calendar'}
            })
            
            nodes.append(event_node)
            
            # Create Person nodes for organizer
            if organizer.get('email'):
                organizer_node, organizer_rel = self._create_person_with_relationship(
                    email=organizer.get('email'),
                    name=organizer.get('displayName'),
                    event_node_id=node_id,
                    rel_type=RelationType.ORGANIZED_BY
                )
                if organizer_node:
                    nodes.append(organizer_node)
                    event_node.relationships.append(organizer_rel)
            
            # Create Person nodes for attendees
            for attendee in attendees:
                email = attendee.get('email')
                if not email:
                    continue
                
                attendee_node, attendee_rel = self._create_person_with_relationship(
                    email=email,
                    name=attendee.get('displayName'),
                    event_node_id=node_id,
                    rel_type=RelationType.ATTENDED_BY
                )
                if attendee_node:
                    nodes.append(attendee_node)
                    event_node.relationships.append(attendee_rel)
            
            return nodes
            
        except Exception as e:
            logger.warning(f"[CalendarCrawler] Transform failed for event: {e}")
            return None
    
    def _create_person_with_relationship(
        self,
        email: str,
        name: Optional[str],
        event_node_id: str,
        rel_type: RelationType
    ) -> tuple:
        """Create a Person node and relationship to an event."""
        # Normalize email
        email_lower = email.lower().strip()
        
        # Generate consistent person node ID using centralized utility
        from src.services.indexing.node_id_utils import generate_person_id
        person_node_id = generate_person_id(email=email_lower)
        
        person_node = ParsedNode(
            node_id=person_node_id,
            node_type=NodeType.PERSON,
            properties={
                'name': name or email.split('@')[0],
                'email': email_lower,
                'source': 'google_calendar',
            },
            searchable_text=f"{name or ''} {email_lower}"
        )
        
        relationship = Relationship(
            from_node=event_node_id,
            to_node=person_node_id,
            rel_type=rel_type
        )
        
        return person_node, relationship
    
    async def detect_conflicts(self) -> List[Dict[str, Any]]:
        """
        Detect scheduling conflicts between events.
        Creates OVERLAPS relationships for conflicting events.
        
        Returns:
            List of conflict details
        """
        if not self.graph_manager:
            return []
        
        conflicts = []
        
        try:
            # Native AQL query for robust overlap detection
            # Uses CalendarEvent collection and OVERLAPS edge collection directly
            query = """
            FOR e1 IN CalendarEvent
              FILTER e1.user_id == @user_id
              FOR e2 IN CalendarEvent
                FILTER e2.user_id == @user_id
                FILTER e1.id < e2.id
                FILTER e1.start_time < e2.end_time
                FILTER e1.end_time > e2.start_time
                
                // Check if overlap relationship already exists
                LET overlap_exists = LENGTH(
                    FOR v IN 1..1 ANY e1 OVERLAPS
                    FILTER v._id == e2._id
                    LIMIT 1
                    RETURN 1
                ) > 0
                
                FILTER !overlap_exists
                LIMIT 50
                RETURN {
                    event1_id: e1.id, 
                    event1_title: e1.title,
                    event2_id: e2.id, 
                    event2_title: e2.title,
                    start1: e1.start_time, 
                    start2: e2.start_time
                }
            """
            
            # Using execute_query which handles AQL execution specifically
            # Note: We pass the query as is, execute_query in manager.py checks for MATCH to determine if translation is needed.
            # This AQL query does not contain MATCH, so it will be executed directly.
            overlaps = await self.graph_manager.execute_query(query, {
                'user_id': self.user_id
            })
            
            for overlap in overlaps or []:
                # Create OVERLAPS relationship
                await self.graph_manager.create_relationship(
                    from_id=overlap['event1_id'],
                    to_id=overlap['event2_id'],
                    relation_type=RelationType.OVERLAPS,
                    properties={
                        'detected_at': datetime.utcnow().isoformat()
                    }
                )
                
                conflicts.append({
                    'event1': overlap['event1_title'],
                    'event2': overlap['event2_title'],
                    'start1': overlap['start1'],
                    'start2': overlap['start2']
                })
            
            if conflicts:
                logger.info(f"[CalendarCrawler] Detected {len(conflicts)} scheduling conflicts")
            
            return conflicts
            
        except Exception as e:
            logger.error(f"[CalendarCrawler] Conflict detection failed: {e}")
            return []
    
    async def run_sync_cycle(self) -> int:
        """Override to add conflict detection and document correlation after indexing."""
        count = await super().run_sync_cycle()
        
        # Run conflict detection after indexing
        if count > 0 and self.graph_manager:
            await self.detect_conflicts()
            # Correlate calendar events with Drive documents
            await self._correlate_events_with_documents()
        
        return count

    async def _correlate_events_with_documents(self):
        """
        Find and link Drive documents to upcoming calendar events.
        
        This enables proactive meeting prep by discovering relevant docs
        for meetings happening in the next 24 hours.
        """
        if not self.cross_app_correlator:
            return
            
        try:
            from datetime import datetime, timedelta
            
            # Focus on events in next 24 hours for proactive prep
            now = datetime.utcnow()
            lookahead_hours = 24
            
            # Get recently indexed events from cache
            for event_id, _ in list(self._event_cache.items())[:20]:  # Limit to 20 events
                try:
                    event_node_id = f"calendar_event_{event_id.replace('-', '_').replace('@', '_')}"
                    
                    # Get event from graph to access details
                    event_node = self.graph_manager.get_node(event_node_id) if self.graph_manager else None
                    if not event_node:
                        continue
                    
                    event_title = event_node.get('title', '')
                    event_description = event_node.get('description', '')
                    
                    if not event_title:
                        continue
                    
                    # Get attendees (would need to query graph for attendee relationships)
                    # For now, use empty list - semantic search is still valuable
                    attendee_emails = []
                    
                    # Find related Drive documents
                    related_docs = await self.cross_app_correlator.find_related_documents_for_meeting(
                        event_node_id=event_node_id,
                        event_title=event_title,
                        event_description=event_description,
                        attendee_emails=attendee_emails,
                        user_id=self.user_id,
                        max_docs=3
                    )
                    
                    if related_docs:
                        logger.debug(
                            f"[CalendarCrawler] Found {len(related_docs)} docs for event '{event_title}'"
                        )
                        
                except Exception as e:
                    logger.debug(f"[CalendarCrawler] Event correlation failed: {e}")
                    
        except Exception as e:
            logger.warning(f"[CalendarCrawler] Document correlation failed: {e}")

