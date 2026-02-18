"""
Event Stream Handler

Processes real-time events from webhooks (Slack, Gmail push notifications, etc.)
for immediate indexing and insight generation.

Unlike the periodic crawlers, this handles events as they arrive for
instant graph updates and proactive notifications.
"""
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph import KnowledgeGraphManager
from src.services.indexing.hybrid_index import HybridIndexCoordinator
from src.ai.rag import RAGEngine

logger = setup_logger(__name__)


class EventType(str, Enum):
    """Supported real-time event types"""
    SLACK_MESSAGE = "slack_message"
    SLACK_REACTION = "slack_reaction" 
    GMAIL_PUSH = "gmail_push"
    CALENDAR_UPDATE = "calendar_update"
    NOTION_UPDATE = "notion_update"
    DRIVE_UPDATE = "drive_update"  # Google Drive file changes


# Maps internal stream event types → outbound WebhookEventType values.
# Used to automatically trigger outbound webhooks after successful indexing.
EVENT_TO_WEBHOOK_TYPE: Dict[str, str] = {
    EventType.SLACK_MESSAGE: "slack.message.received",
    EventType.SLACK_REACTION: "slack.reaction.added",
    EventType.GMAIL_PUSH: "email.received",
    EventType.CALENDAR_UPDATE: "calendar.event.updated",
}


class EventStreamHandler:
    """
    Processes real-time events from webhooks for immediate graph updates.
    
    Features:
    - Immediate indexing of incoming events
    - Topic extraction for new content
    - Temporal linking for time-based queries
    - Relationship strength reinforcement
    - Immediate insight generation
    - Event deduplication
    """
    
    def __init__(
        self,
        config: Config,
        rag_engine: Optional[RAGEngine] = None,
        graph_manager: Optional[KnowledgeGraphManager] = None,
        topic_extractor: Optional[Any] = None,
        temporal_indexer: Optional[Any] = None,
        relationship_manager: Optional[Any] = None,
        insight_service: Optional[Any] = None
    ):
        self.config = config
        self.rag_engine = rag_engine
        self.graph_manager = graph_manager
        self.topic_extractor = topic_extractor
        self.temporal_indexer = temporal_indexer
        self.relationship_manager = relationship_manager
        self.insight_service = insight_service
        
        # Initialize hybrid coordinator
        if rag_engine and graph_manager:
            self.hybrid_index = HybridIndexCoordinator(
                graph_manager=graph_manager,
                rag_engine=rag_engine
            )
        else:
            self.hybrid_index = None
            
        # Track recently processed events to avoid duplicates
        self._processed_events: Dict[str, datetime] = {}
        from src.services.service_constants import ServiceConstants
        self._event_ttl_seconds = ServiceConstants.EVENT_TTL_SECONDS
        
        # Metrics
        self._events_processed = 0
        self._events_skipped = 0
        
        # User crawlers cache for immediate fetch
        self._user_crawlers: Dict[int, Dict[str, Any]] = {}
        
    async def handle_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        user_id: int
    ) -> Dict[str, Any]:
        """
        Route and process an incoming real-time event.
        
        Args:
            event_type: Type of event (slack_message, gmail_push, etc.)
            payload: Raw event payload from webhook
            user_id: User ID this event belongs to
            
        Returns:
            Processing result with status and any generated insights
        """
        result = {
            "status": "received",
            "event_type": event_type,
            "user_id": user_id,
            "indexed": False,
            "insights": []
        }
        
        # Generate unique event ID for deduplication
        event_id = self._generate_event_id(event_type, payload)
        
        # Check for duplicate
        if self._is_duplicate(event_id):
            self._events_skipped += 1
            result["status"] = "skipped_duplicate"
            return result
            
        # Mark as processed
        self._processed_events[event_id] = datetime.utcnow()
        self._cleanup_old_events()
        
        try:
            # Route to appropriate handler
            if event_type == EventType.SLACK_MESSAGE:
                nodes = await self._handle_slack_message(payload, user_id)
            elif event_type == EventType.SLACK_REACTION:
                nodes = await self._handle_slack_reaction(payload, user_id)
            elif event_type == EventType.GMAIL_PUSH:
                nodes = await self._handle_gmail_push(payload, user_id)
            elif event_type == EventType.CALENDAR_UPDATE:
                nodes = await self._handle_calendar_update(payload, user_id)
            elif event_type == EventType.NOTION_UPDATE:
                nodes = await self._handle_notion_update(payload, user_id)
            elif event_type == EventType.DRIVE_UPDATE:
                nodes = await self._handle_drive_update(payload, user_id)
            else:
                logger.warning(f"[EventStream] Unknown event type: {event_type}")
                result["status"] = "unknown_type"
                return result
                
            # Index generated nodes
            if nodes and self.hybrid_index:
                success, _ = await self.hybrid_index.index_batch(nodes)
                if success:
                    result["indexed"] = True
                    self._events_processed += 1
                    
                    # 1. Extract topics from content
                    await self._extract_topics(nodes, user_id)
                    
                    # 2. Link to TimeBlocks for temporal queries
                    await self._link_temporal(nodes, user_id)
                    
                    # 3. Reinforce relationship strengths
                    await self._reinforce_relationships(nodes)
                    
                    # 4. Generate immediate insights
                    insights = await self._generate_immediate_insights(nodes, user_id)
                    result["insights"] = insights
                    
            result["status"] = "processed"
            
            # 5. Trigger outbound webhooks if a mapping exists
            self._trigger_outbound_webhook(
                event_type=event_type,
                event_id=event_id,
                payload=payload,
                user_id=user_id,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[EventStream] Error processing {event_type}: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            return result
            
    async def _handle_slack_message(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """Process a real-time Slack message event"""
        from src.services.indexing.graph.schema import NodeType, RelationType
        
        event = payload.get("event", payload)
        text = event.get("text", "")
        slack_user_id = event.get("user")
        channel_id = event.get("channel")
        ts = event.get("ts")
        
        if not text or not ts:
            return []
            
        # Create message node
        message_node = ParsedNode(
            node_id=f"message_slack_{ts.replace('.', '_')}",
            node_type=NodeType.MESSAGE.value,
            properties={
                'text': text,
                'slack_message_ts': ts,
                'slack_thread_ts': event.get('thread_ts'),  # Track thread for detection
                'slack_user_id': slack_user_id,
                'slack_channel_id': channel_id,
                'timestamp': datetime.fromtimestamp(float(ts)).isoformat(),
                'source': 'slack',
                'real_time': True  # Mark as real-time processed
            },
            searchable_text=text
        )
        
        # Check for heated thread (potential bug report without ticket)
        heated_insight = await self._detect_heated_thread(event, user_id)
        if heated_insight:
            # Store as insight for delivery
            if self.insight_service:
                try:
                    await self.insight_service.store_insight(heated_insight, user_id)
                except Exception as e:
                    logger.debug(f"[EventStream] Failed to store heated thread insight: {e}")
            # Trigger immediate delivery for high priority
            if heated_insight.get('priority') in ('critical', 'high'):
                await self._deliver_urgent_insights([heated_insight], user_id)
        
        logger.debug(f"[EventStream] Processed Slack message in channel {channel_id}")
        return [message_node]
        
    async def _handle_slack_reaction(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """Process a Slack reaction event (for relationship enrichment)"""
        # Reactions don't create new nodes, but can update relationship strength
        # This is a placeholder for relationship strength updates
        event = payload.get("event", payload)
        reaction = event.get("reaction")
        item = event.get("item", {})
        
        logger.debug(f"[EventStream] Received reaction :{reaction}: (relationship update pending)")
        return []
        
    async def _handle_gmail_push(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """
        Process Gmail push notification with IMMEDIATE email fetch.
        
        Instead of waiting for the periodic crawler, this fetches and indexes
        the new email right away for real-time updates.
        """
        history_id = payload.get("historyId")
        
        logger.info(f"[EventStream] Gmail push for user {user_id}, historyId: {history_id}")
        
        try:
            # Get unified indexer to access email crawler
            from src.services.indexing.unified_indexer import get_unified_indexer
            
            indexer_service = get_unified_indexer()
            
            # Find the email crawler for this user
            email_crawler = None
            for indexer in indexer_service.indexers:
                if indexer.name == "email" and indexer.user_id == user_id:
                    email_crawler = indexer
                    break
            
            if not email_crawler:
                logger.debug(f"[EventStream] No email crawler for user {user_id}")
                return []
            
            # Trigger immediate sync (fetch and transform)
            items = await email_crawler.fetch_delta()
            
            nodes = []
            for item in items[:5]:  # Limit to 5 to avoid blocking
                result = await email_crawler.transform_item(item)
                if result:
                    if isinstance(result, list):
                        nodes.extend(result)
                    else:
                        nodes.append(result)
            
            logger.info(f"[EventStream] Immediately indexed {len(nodes)} email nodes")
            return nodes
            
        except Exception as e:
            logger.error(f"[EventStream] Gmail immediate fetch failed: {e}")
            return []
        
    async def _handle_calendar_update(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """
        Process Google Calendar update webhook with IMMEDIATE event fetch.
        
        Fetches the updated calendar event immediately instead of waiting
        for the periodic crawler.
        """
        from src.services.indexing.graph.schema import NodeType
        
        resource_id = payload.get("resourceId")
        channel_id = payload.get("channelId")
        event_id = payload.get("eventId")  # May be present for specific event updates
        
        logger.info(f"[EventStream] Calendar update for resource {resource_id}")
        
        try:
            from src.services.indexing.unified_indexer import get_unified_indexer
            
            indexer_service = get_unified_indexer()
            
            # Find the calendar crawler for this user
            calendar_crawler = None
            for indexer in indexer_service.indexers:
                if indexer.name == "calendar" and indexer.user_id == user_id:
                    calendar_crawler = indexer
                    break
            
            if not calendar_crawler:
                logger.debug(f"[EventStream] No calendar crawler for user {user_id}")
                return []
            
            # Trigger immediate sync
            items = await calendar_crawler.fetch_delta()
            
            nodes = []
            for item in items[:10]:  # Limit to 10 events
                result = await calendar_crawler.transform_item(item)
                if result:
                    if isinstance(result, list):
                        nodes.extend(result)
                    else:
                        nodes.append(result)
            
            logger.info(f"[EventStream] Immediately indexed {len(nodes)} calendar nodes")
            return nodes
            
        except Exception as e:
            logger.error(f"[EventStream] Calendar immediate fetch failed: {e}")
            return []

    async def _handle_notion_update(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """
        Process Notion webhook with IMMEDIATE page fetch.
        
        Fetches and indexes the updated Notion page immediately.
        """
        page_id = payload.get("page_id") or payload.get("id")
        
        logger.info(f"[EventStream] Notion update for page {page_id}, user {user_id}")
        
        try:
            from src.services.indexing.unified_indexer import get_unified_indexer
            
            indexer_service = get_unified_indexer()
            
            # Find the Notion crawler for this user
            notion_crawler = None
            for indexer in indexer_service.indexers:
                if indexer.name == "notion" and indexer.user_id == user_id:
                    notion_crawler = indexer
                    break
            
            if not notion_crawler:
                logger.debug(f"[EventStream] No Notion crawler for user {user_id}")
                return []
            
            # If we have a specific page_id, fetch just that page
            if page_id and hasattr(notion_crawler, 'notion_client'):
                import asyncio
                page = await asyncio.to_thread(
                    notion_crawler.notion_client.get_page,
                    page_id
                )
                
                if page:
                    result = await notion_crawler.transform_item(page)
                    if result:
                        logger.info(f"[EventStream] Immediately indexed Notion page {page_id}")
                        return result if isinstance(result, list) else [result]
            
            # Fallback: trigger full sync
            items = await notion_crawler.fetch_delta()
            nodes = []
            for item in items[:5]:
                result = await notion_crawler.transform_item(item)
                if result:
                    if isinstance(result, list):
                        nodes.extend(result)
                    else:
                        nodes.append(result)
            
            return nodes
            
        except Exception as e:
            logger.error(f"[EventStream] Notion immediate fetch failed: {e}")
            return []

    async def _handle_drive_update(
        self,
        payload: Dict[str, Any],
        user_id: int
    ) -> List[ParsedNode]:
        """
        Process Google Drive webhook with IMMEDIATE file fetch.
        
        Fetches and indexes changed files immediately instead of waiting
        for the periodic crawler. This enables real-time indexing when users
        create, modify, or upload files to Drive.
        
        Payload from Drive API push notifications contains:
        - kind: "api#channel"
        - id: channel ID
        - resourceId: ID of the watched resource
        - resourceUri: URI of the resource
        - token: channel token (contains user info)
        - expiration: channel expiration time
        - x-goog-changed: comma-separated list of changes (sync, content, properties, etc.)
        """
        resource_id = payload.get("resourceId")
        resource_uri = payload.get("resourceUri")
        changed = payload.get("x-goog-changed", "")
        
        logger.info(
            f"[EventStream] Drive update for user {user_id}, "
            f"resource: {resource_id}, changes: {changed}"
        )
        
        # Skip sync notifications (these are just channel confirmations)
        if changed == "sync":
            logger.debug("[EventStream] Drive sync notification, skipping")
            return []
        
        try:
            from src.services.indexing.unified_indexer import get_unified_indexer
            
            indexer_service = get_unified_indexer()
            
            # Find the Drive crawler for this user
            drive_crawler = None
            for indexer in indexer_service.indexers:
                if indexer.name == "drive" and indexer.user_id == user_id:
                    drive_crawler = indexer
                    break
            
            if not drive_crawler:
                logger.debug(f"[EventStream] No Drive crawler for user {user_id}")
                return []
            
            # Trigger immediate sync - fetch changed files
            items = await drive_crawler.fetch_delta()
            
            nodes = []
            for item in items[:10]:  # Limit to 10 files to avoid blocking
                result = await drive_crawler.transform_item(item)
                if result:
                    if isinstance(result, list):
                        nodes.extend(result)
                    else:
                        nodes.append(result)
            
            logger.info(f"[EventStream] Immediately indexed {len(nodes)} Drive nodes")
            return nodes
            
        except Exception as e:
            logger.error(f"[EventStream] Drive immediate fetch failed: {e}")
            return []
        
        
    async def _extract_topics(self, nodes: List[ParsedNode], user_id: int):
        """Extract topics from processed nodes"""
        if not self.topic_extractor:
            return
            
        for node in nodes:
            if node.searchable_text and len(node.searchable_text) > 50:
                try:
                    await self.topic_extractor.extract_topics(
                        content=node.searchable_text,
                        source="realtime",
                        source_node_id=node.node_id,
                        user_id=user_id
                    )
                except Exception as e:
                    logger.debug(f"[EventStream] Topic extraction failed: {e}")

    async def _link_temporal(self, nodes: List[ParsedNode], user_id: int):
        """Link nodes to TimeBlocks for temporal queries."""
        if not self.temporal_indexer:
            return
            
        for node in nodes:
            try:
                # Get timestamp from node properties
                timestamp_str = (
                    node.properties.get('timestamp') or 
                    node.properties.get('created_at') or
                    node.properties.get('date')
                )
                
                if not timestamp_str:
                    continue
                
                # Parse timestamp
                if isinstance(timestamp_str, str):
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        continue
                else:
                    timestamp = timestamp_str
                
                # Link to TimeBlock
                await self.temporal_indexer.link_event_to_timeblock(
                    event_id=node.node_id,
                    timestamp=timestamp,
                    granularity="day",
                    user_id=user_id
                )
                
            except Exception as e:
                logger.debug(f"[EventStream] Temporal linking failed: {e}")

    async def _reinforce_relationships(self, nodes: List[ParsedNode]):
        """Reinforce relationship strengths for indexed nodes."""
        if not self.relationship_manager:
            return
            
        for node in nodes:
            try:
                relationships = getattr(node, 'relationships', [])
                for rel in relationships:
                    await self.relationship_manager.reinforce_relationship(
                        from_id=rel.from_node,
                        to_id=rel.to_node,
                        rel_type=rel.rel_type,
                        interaction_weight=1.5  # Boost for real-time events
                    )
            except Exception as e:
                logger.debug(f"[EventStream] Relationship reinforcement failed: {e}")

    async def _generate_immediate_insights(
        self,
        nodes: List[ParsedNode],
        user_id: int
    ) -> List[Dict[str, Any]]:
        """
        Generate immediate insights from newly indexed content.
        
        Checks for:
        - Calendar conflicts with existing events
        - Connections to topics in recent discussions
        - Urgent action items
        - Person context (OOO, recent activity)
        """
        insights = []
        
        if not self.graph_manager:
            return insights
        
        for node in nodes:
            try:
                # 1. Check for calendar conflicts
                if node.node_type in ['CalendarEvent', 'Calendar_Event']:
                    conflict_insights = await self._check_calendar_conflicts(node, user_id)
                    insights.extend(conflict_insights)
                
                # 2. Check for topic connections to recent content
                if node.searchable_text and len(node.searchable_text) > 50:
                    connection_insights = await self._find_topic_connections(node, user_id)
                    insights.extend(connection_insights)
                
                # 3. Check for person-related insights
                person_insights = await self._check_person_context(node, user_id)
                insights.extend(person_insights)
                
            except Exception as e:
                logger.debug(f"[EventStream] Insight generation failed for {node.node_id}: {e}")
        
        # Classify priority for each insight
        for insight in insights:
            insight_type = insight.get('type', '')
            if insight_type in ('calendar_conflict', 'urgent_action'):
                insight['priority'] = 'critical'
            elif insight_type in ('topic_connection', 'person_ooo'):
                insight['priority'] = 'high'
            else:
                insight['priority'] = 'medium'
        
        # Store high-confidence insights in the graph
        if self.insight_service and insights:
            for insight in insights:
                if insight.get('confidence', 0) >= 0.7:
                    try:
                        await self.insight_service.store_insight(insight, user_id)
                    except Exception as e:
                        logger.debug(f"[EventStream] Failed to store insight: {e}")
        
        # PRIORITY BYPASS: Immediately deliver critical insights
        critical_insights = [i for i in insights if i.get('priority') == 'critical']
        if critical_insights:
            await self._deliver_urgent_insights(critical_insights, user_id)
        
        return insights

    async def _check_calendar_conflicts(
        self,
        node: ParsedNode,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """Check for scheduling conflicts with existing calendar events."""
        insights = []
        
        start_time = node.properties.get('start_time')
        end_time = node.properties.get('end_time')
        
        if not start_time or not end_time:
            return insights
        
        try:
            # Query for overlapping events - AQL version
            query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND e.id != @event_id
                   AND e.start_time < @end_time
                   AND e.end_time > @start_time
                SORT e.start_time ASC
                LIMIT 20
                RETURN {
                    id: e.id,
                    title: e.title,
                    start_time: e.start_time
                }
            """
            
            result = await self.graph_manager.execute_query(query, {
                'user_id': user_id,
                'event_id': node.node_id,
                'start_time': start_time,
                'end_time': end_time
            })
            
            for conflict in result or []:
                new_title = node.properties.get('title', 'New event')
                conflict_title = conflict.get('title', 'existing event')
                insights.append({
                    'type': 'calendar_conflict',
                    'title': "Scheduling conflict detected",
                    'description': f"'{new_title}' overlaps with '{conflict_title}'",
                    'content': f"'{new_title}' overlaps with '{conflict_title}'. Would you like to reschedule?",
                    'source_node_id': node.node_id,
                    'related_node_id': conflict.get('id'),
                    'confidence': 0.95,
                    'urgency': 'high',
                    'timestamp': datetime.utcnow().isoformat(),
                    'actions': [
                        {'type': 'reschedule', 'label': f"Reschedule '{new_title}'", 'event_id': node.node_id},
                        {'type': 'decline', 'label': f"Decline '{new_title}'", 'event_id': node.node_id},
                        {'type': 'dismiss', 'label': 'Keep both'}
                    ]
                })
                
        except Exception as e:
            logger.debug(f"[EventStream] Conflict check failed: {e}")
        
        return insights

    async def _find_topic_connections(
        self,
        node: ParsedNode,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """Find connections between new content and existing topics."""
        insights = []
        
        # This is a lightweight check - full topic extraction happens separately
        # Here we just look for keywords that match existing topic nodes
        
        try:
            keywords = self._extract_keywords(node.searchable_text)
            if not keywords:
                return insights
            
            # Query for matching topics - AQL version
            query = """
            FOR t IN Topic
                FILTER t.user_id == @user_id AND t.name IN @keywords
                LET recent_content = (
                    FOR edge IN DISCUSSES
                        FILTER edge._to == t._id
                        LET content = DOCUMENT(edge._from)
                        LIMIT 3
                        RETURN content.id
                )
                SORT LENGTH(recent_content) DESC
                LIMIT 3
                RETURN {
                    topic: t.name,
                    related_ids: recent_content,
                    connection_count: LENGTH(recent_content)
                }
            """
            
            result = await self.graph_manager.execute_query(query, {
                'user_id': user_id,
                'keywords': keywords[:10]  # Limit keywords
            })
            
            for topic in result or []:
                if topic.get('connection_count', 0) >= 2:
                    insights.append({
                        'type': 'topic_connection',
                        'title': f"Related to topic: {topic.get('topic')}",
                        'description': f"This content connects to {topic.get('connection_count')} other items discussing '{topic.get('topic')}'",
                        'source_node_id': node.node_id,
                        'topic': topic.get('topic'),
                        'confidence': 0.7,
                        'urgency': 'low',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
        except Exception as e:
            logger.debug(f"[EventStream] Topic connection check failed: {e}")
        
        return insights

    async def _check_person_context(
        self,
        node: ParsedNode,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """Check for person-related context (OOO, recent activity)."""
        insights = []
        
        # Look for person mentions in the node
        mentioned_emails = self._extract_emails(node.searchable_text or '')
        
        if not mentioned_emails:
            return insights
        
        try:
            # Check for OOO status or recent activity
            for email in mentioned_emails[:3]:  # Limit to 3 people
                query = """
                FOR p IN Person
                    FILTER p.email == @email
                    LET recent_emails = (
                        FOR edge IN UNION(
                            (FOR e IN SENT FILTER e._from == p._id RETURN e),
                            (FOR e IN RECEIVED FILTER e._to == p._id RETURN e)
                        )
                            LET m = DOCUMENT(edge._from == p._id ? edge._to : edge._from)
                            FILTER m.node_type == 'Email' AND m.timestamp > DATE_SUBTRACT(DATE_NOW(), 7, 'day')
                            RETURN m
                    )
                    RETURN {
                        name: p.name,
                        email: p.email,
                        recent_activity: LENGTH(recent_emails),
                        is_ooo: p.is_ooo
                    }
                """
                
                result = await self.graph_manager.execute_query(query, {
                    'email': email.lower()
                })
                
                for person in result or []:
                    if person.get('is_ooo'):
                        insights.append({
                            'type': 'person_ooo',
                            'title': f"{person.get('name', email)} is out of office",
                            'description': f"This person may not respond immediately",
                            'source_node_id': node.node_id,
                            'person_email': email,
                            'confidence': 0.85,
                            'urgency': 'medium',
                            'timestamp': datetime.utcnow().isoformat()
                        })
                        
        except Exception as e:
            logger.debug(f"[EventStream] Person context check failed: {e}")
        
        return insights

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract potential topic keywords from text."""
        if not text:
            return []
        
        import re
        
        # Simple keyword extraction - remove common words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'can', 'to', 'of',
                      'in', 'for', 'on', 'with', 'at', 'by', 'from', 'or', 'and',
                      'this', 'that', 'these', 'those', 'it', 'its', 'i', 'me', 'my',
                      'we', 'our', 'you', 'your', 'they', 'their', 'he', 'she', 'him', 'her'}
        
        # Extract words, filter, and take most significant
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]
        
        # Return unique keywords
        return list(dict.fromkeys(keywords))[:20]
    
    async def _detect_heated_thread(
        self,
        event: Dict[str, Any],
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if a Slack thread looks like a bug report without an associated ticket.
        
        This is the "Ghost Collaborator" feature - watching for signals that suggest
        a bug/issue is being discussed but no ticket has been created.
        """
        text = event.get('text', '').lower()
        thread_ts = event.get('thread_ts') or event.get('ts')
        channel_id = event.get('channel')
        
        if not text or not thread_ts:
            return None
        
        # Simple keyword heuristics for bug/issue detection
        bug_signals = [
            'bug', 'broken', 'not working', 'error', 'crash', 'regression',
            'urgent', 'blocker', 'fix this', 'critical', 'production down',
            'failing', 'exception', 'null pointer', 'cannot access'
        ]
        
        # Check if message contains bug signals
        has_bug_signal = any(signal in text for signal in bug_signals)
        if not has_bug_signal:
            return None
        
        # Check if there's already a Linear issue linked to this thread
        if self.graph_manager:
            try:
                query = """
                FOR m IN Message
                    FILTER m.slack_thread_ts == @thread_ts
                    FOR edge IN REFERENCES
                        FILTER edge._from == m._id
                        LET linked = DOCUMENT(edge._to)
                        FILTER linked.node_type == 'LinearIssue'
                        LIMIT 1
                        RETURN linked
                """
                existing = await self.graph_manager.execute_query(query, {'thread_ts': thread_ts})
                
                if existing:
                    # Already has a ticket, skip
                    return None
                    
            except Exception as e:
                logger.debug(f"[EventStream] Linear check failed: {e}")
        
        # Generate insight with action drafts
        logger.info(f"[EventStream] Detected heated thread in channel {channel_id}")
        return {
            'type': 'bug_report_candidate',
            'title': 'Potential bug report detected',
            'content': "This Slack thread looks like a bug report. Should I draft a Linear issue?",
            'description': f"Detected in channel, thread contains: '{text[:100]}...'",
            'confidence': 0.75,
            'priority': 'high',
            'timestamp': datetime.utcnow().isoformat(),
            'metadata': {
                'thread_ts': thread_ts,
                'channel': channel_id,
                'snippet': text[:200]
            },
            'actions': [
                {
                    'type': 'create_linear_issue',
                    'label': 'Create Linear issue',
                    'metadata': {'thread_ts': thread_ts, 'channel': channel_id}
                },
                {
                    'type': 'dismiss',
                    'label': 'Not a bug'
                }
            ]
        }

    def _extract_emails(self, text: str) -> List[str]:
        """Extract email addresses from text."""
        import re
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return re.findall(pattern, text)
        
    def _generate_event_id(self, event_type: str, payload: Dict[str, Any]) -> str:
        """Generate unique ID for event deduplication"""
        import hashlib
        
        # Use relevant fields based on event type
        if event_type == EventType.SLACK_MESSAGE:
            event = payload.get("event", payload)
            unique_str = f"{event.get('ts')}_{event.get('channel')}"
        elif event_type == EventType.GMAIL_PUSH:
            unique_str = str(payload.get("historyId", ""))
        else:
            unique_str = str(payload)
            
        return hashlib.md5(f"{event_type}_{unique_str}".encode()).hexdigest()[:16]
        
    def _is_duplicate(self, event_id: str) -> bool:
        """Check if event was recently processed"""
        return event_id in self._processed_events
    
    async def _deliver_urgent_insights(
        self,
        insights: List[Dict[str, Any]],
        user_id: int
    ) -> None:
        """
        Immediately deliver critical insights via WebSocket/notification.
        
        This bypasses the normal delivery queue for time-sensitive insights
        like calendar conflicts or urgent action items.
        """
        try:
            from src.services.insights.delivery import InsightDeliveryService
            from src.services.insights.delivery import InsightPriority
            
            # Get or create delivery service
            delivery = InsightDeliveryService(self.config, self.graph_manager)
            
            for insight in insights:
                try:
                    # Attempt WebSocket delivery for real-time notification
                    await delivery._deliver_via_websocket(
                        user_id=user_id,
                        insight=insight,
                        priority=InsightPriority.URGENT
                    )
                    logger.info(
                        f"[EventStream] Urgent insight delivered via WebSocket: "
                        f"{insight.get('type')} for user {user_id}"
                    )
                except Exception as ws_error:
                    logger.debug(f"[EventStream] WebSocket delivery failed: {ws_error}")
                    
                    # Fallback: queue for email delivery
                    try:
                        await delivery._deliver_via_email(
                            user_id=user_id,
                            insight=insight,
                            priority=InsightPriority.URGENT
                        )
                    except Exception as email_error:
                        logger.debug(f"[EventStream] Email delivery also failed: {email_error}")
                        
        except ImportError:
            logger.debug("[EventStream] InsightDeliveryService not available for urgent delivery")
        except Exception as e:
            logger.warning(f"[EventStream] Urgent insight delivery failed: {e}")
        
    def _trigger_outbound_webhook(
        self,
        event_type: str,
        event_id: str,
        payload: Dict[str, Any],
        user_id: int,
    ):
        """
        If *event_type* has a matching outbound webhook type, queue a Celery
        task to deliver the webhook to all active subscribers.
        
        This is fire-and-forget — errors are logged but never break the
        indexing pipeline.
        """
        webhook_type_value = EVENT_TO_WEBHOOK_TYPE.get(event_type)
        if not webhook_type_value:
            return

        try:
            from src.workers.tasks.webhook_tasks import deliver_webhook_task

            deliver_webhook_task.delay(
                event_type=webhook_type_value,
                event_id=event_id,
                payload=payload,
                user_id=user_id,
            )
            logger.debug(
                f"[EventStream] Queued outbound webhook {webhook_type_value} "
                f"for event {event_id}"
            )
        except Exception as e:
            logger.warning(f"[EventStream] Failed to queue outbound webhook: {e}")

    def _cleanup_old_events(self):
        """Remove old events from dedup cache"""
        now = datetime.utcnow()
        expired = [
            eid for eid, ts in self._processed_events.items()
            if (now - ts).total_seconds() > self._event_ttl_seconds
        ]
        for eid in expired:
            del self._processed_events[eid]
            
    def get_stats(self) -> Dict[str, int]:
        """Get processing statistics"""
        return {
            "events_processed": self._events_processed,
            "events_skipped": self._events_skipped,
            "dedup_cache_size": len(self._processed_events)
        }


# Global instance
_event_stream_handler: Optional[EventStreamHandler] = None


def get_event_stream_handler() -> Optional[EventStreamHandler]:
    """Get the global event stream handler instance"""
    return _event_stream_handler


def init_event_stream_handler(
    config: Config,
    rag_engine: Optional[RAGEngine] = None,
    graph_manager: Optional[KnowledgeGraphManager] = None,
    topic_extractor: Optional[Any] = None,
    temporal_indexer: Optional[Any] = None,
    relationship_manager: Optional[Any] = None,
    insight_service: Optional[Any] = None
) -> EventStreamHandler:
    """
    Initialize and return the global event stream handler.
    
    Args:
        config: Application configuration
        rag_engine: RAG engine for vector search
        graph_manager: Knowledge graph manager
        topic_extractor: For extracting topics from content
        temporal_indexer: For linking content to TimeBlocks
        relationship_manager: For tracking relationship strength
        insight_service: For storing generated insights
    """
    global _event_stream_handler
    _event_stream_handler = EventStreamHandler(
        config=config,
        rag_engine=rag_engine,
        graph_manager=graph_manager,
        topic_extractor=topic_extractor,
        temporal_indexer=temporal_indexer,
        relationship_manager=relationship_manager,
        insight_service=insight_service
    )
    logger.info("[EventStream] Handler initialized with real-time processing support")
    return _event_stream_handler
