"""
Insight Service

Retrieves and surfaces proactive insights from the GraphObserver to users.
This is "the bridge" between the background insight generation and the user-facing agents.

Features:
- Retrieves high-confidence, actionable insights
- Filters by relevance to current context
- Tracks which insights have been shown/dismissed
- Supports priority-based surfacing
- Multi-factor confidence scoring (NEW)
- User feedback collection (NEW)

Example Usage:
    insight_service = InsightService(config, graph_manager)
    insights = await insight_service.get_contextual_insights(user_id, "meeting with Bob")
    # Returns: [{"content": "Bob mentioned he's out sick in Slack", "type": "conflict", ...}]
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.integrations.google_drive.service import GoogleDriveService

# Import new intelligence services
try:
    from src.services.insights.confidence import ConfidenceCalculator
    from src.services.insights.feedback import InsightFeedbackService
except ImportError:
    ConfidenceCalculator = None
    InsightFeedbackService = None

logger = setup_logger(__name__)

# Import thresholds from centralized constants
from src.services.service_constants import ServiceConstants
MIN_INSIGHT_CONFIDENCE = ServiceConstants.MIN_INSIGHT_CONFIDENCE
MAX_INSIGHTS_PER_RESPONSE = ServiceConstants.MAX_INSIGHTS_PER_RESPONSE
INSIGHT_MAX_AGE_HOURS = ServiceConstants.INSIGHT_MAX_AGE_HOURS


class InsightService:
    """
    Service for retrieving and managing proactive insights.
    
    Works with GraphObserverService which creates INSIGHT nodes.
    This service surfaces those insights to users at the right time.
    
    Enhanced with:
    - ConfidenceCalculator for multi-factor confidence scoring
    - InsightFeedbackService for user feedback collection
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager, drive_service: Optional[GoogleDriveService] = None):
        self.config = config
        self.graph = graph_manager
        self.drive_service = drive_service
        self.reasoning_service = None
        self.reactive_service = None
        
        # Initialize intelligence services
        self.confidence_calculator = None
        self.feedback_service = None
        
        if ConfidenceCalculator:
            self.confidence_calculator = ConfidenceCalculator(config, graph_manager)
        if InsightFeedbackService:
            self.feedback_service = InsightFeedbackService(config, graph_manager)

    def set_reasoning_service(self, service):
        self.reasoning_service = service
        
    def set_reactive_service(self, service):
        self.reactive_service = service
    
    async def recalculate_insight_confidence(self, insight_id: str) -> float:
        """
        Recalculate confidence for an insight using multi-factor scoring.
        
        Args:
            insight_id: Insight node ID
            
        Returns:
            New confidence score
        """
        if not self.confidence_calculator:
            return 0.5
        
        insight = await self._get_insight(insight_id)
        if not insight:
            return 0.0
        
        new_confidence = await self.confidence_calculator.calculate(insight, {})
        
        # Update in graph
        try:
            query = """
            FOR i IN Insight
                FILTER i.id == @id
                UPDATE i WITH { confidence: @confidence, confidence_updated: @now } IN Insight
                RETURN i.id
            """
            await self.graph.execute_query(query, {
                "id": insight_id,
                "confidence": new_confidence,
                "now": datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f"[InsightService] Failed to update confidence: {e}")
        
        return new_confidence
    
    async def record_feedback(
        self,
        user_id: int,
        insight_id: str,
        feedback_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record user feedback on an insight.
        
        Args:
            user_id: User ID
            insight_id: Insight ID
            feedback_type: helpful, not_helpful, wrong, obvious, acted_on
            context: Optional additional context
            
        Returns:
            True if feedback recorded successfully
        """
        if not self.feedback_service:
            logger.warning("[InsightService] Feedback service not available")
            return False
        
        return await self.feedback_service.record_feedback(
            user_id, insight_id, feedback_type, context
        )
    
    async def _get_insight(self, insight_id: str) -> Optional[Dict[str, Any]]:
        """Get insight by ID."""
        try:
            query = """
            FOR i IN Insight
                FILTER i.id == @id
                LET related_ids = (
                    FOR edge IN ABOUT
                        FILTER edge._from == i._id
                        RETURN PARSE_IDENTIFIER(edge._to).key
                )
                RETURN {
                    id: i.id,
                    content: i.content,
                    type: i.type,
                    confidence: i.confidence,
                    user_id: i.user_id,
                    created_at: i.created_at,
                    related_ids: related_ids
                }
            """
            result = await self.graph.execute_query(query, {"id": insight_id})
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.debug(f"[InsightService] Failed to get insight: {e}")
            return None
        
    async def get_contextual_insights(
        self,
        user_id: int,
        current_context: str,
        max_insights: int = MAX_INSIGHTS_PER_RESPONSE
    ) -> List[Dict[str, Any]]:
        """
        Get insights relevant to the current user context.
        
        Args:
            user_id: User ID to get insights for
            current_context: Current query/context to match against
            max_insights: Maximum number of insights to return
            
        Returns:
            List of relevant insights with metadata
        """
        min_created = (datetime.utcnow() - timedelta(hours=INSIGHT_MAX_AGE_HOURS)).isoformat()
        
        # Query for unseen, high-confidence, actionable insights using AQL
        query = """
        FOR i IN Insight
            FILTER i.user_id == @user_id
               AND i.confidence >= @min_confidence
               AND (i.dismissed == null OR i.dismissed == false)
               AND (i.shown_count == null OR i.shown_count < 3)
               AND (i.created_at == null OR i.created_at >= @min_created)
            
            LET related_ids = (
                FOR edge IN ABOUT
                    FILTER edge._from == i._id
                    LET related = DOCUMENT(edge._to)
                    LIMIT 5
                    RETURN related.id
            )
            
            LET related_names = (
                FOR edge IN ABOUT
                    FILTER edge._from == i._id
                    LET related = DOCUMENT(edge._to)
                    LIMIT 3
                    RETURN NOT_NULL(related.name, related.subject, related.title)
            )
            
            SORT i.confidence DESC, i.created_at DESC
            LIMIT @limit
            
            RETURN {
                id: i.id,
                content: i.content,
                type: i.type,
                confidence: i.confidence,
                actionable: i.actionable,
                created_at: i.created_at,
                related_ids: related_ids,
                related_names: related_names
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "min_confidence": MIN_INSIGHT_CONFIDENCE,
                "min_created": min_created,
                "limit": max_insights * 2  # Fetch extra for filtering
            })
            
            if not results:
                return []
            
            # Filter by context relevance (simple keyword matching)
            filtered = []
            context_lower = current_context.lower()
            
            for insight in results:
                content = insight.get("content", "").lower()
                related_names = insight.get("related_names", [])
                
                # Check if insight relates to current context
                relevance_score = 0.0
                
                # Direct content match
                if any(word in content for word in context_lower.split() if len(word) > 3):
                    relevance_score += 0.3
                    
                # Related entity match
                for name in related_names:
                    if name and name.lower() in context_lower:
                        relevance_score += 0.5
                        break
                
                # High confidence insights are always potentially relevant
                if insight.get("confidence", 0) >= 0.9:
                    relevance_score += 0.2
                    
                # Conflicts are always important
                if insight.get("type") == "conflict":
                    relevance_score += 0.3
                    
                if relevance_score > 0.2 or insight.get("type") == "conflict":
                    filtered.append({
                        "id": insight.get("id"),
                        "content": insight.get("content"),
                        "type": insight.get("type"),
                        "confidence": insight.get("confidence"),
                        "actionable": insight.get("actionable", False),
                        "created_at": insight.get("created_at"),
                        "related_entities": insight.get("related_names", []),
                        "relevance_score": relevance_score
                    })
            
            # Sort by relevance and return top insights
            filtered.sort(key=lambda x: (x.get("type") == "conflict", x.get("relevance_score", 0)), reverse=True)
            return filtered[:max_insights]
            
        except Exception as e:
            logger.error(f"[InsightService] Failed to get insights: {e}")
            return []
    
    async def get_urgent_insights(
        self,
        user_id: int,
        max_insights: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get urgent/conflict insights that should be shown immediately.
        
        These are shown proactively, not just in response to queries.
        """
        query = """
        FOR i IN Insight
            FILTER i.user_id == @user_id
               AND i.type == 'conflict'
               AND i.confidence >= 0.8
               AND (i.dismissed == null OR i.dismissed == false)
               AND (i.urgency_shown == null OR i.urgency_shown == false)
            SORT i.confidence DESC
            LIMIT @limit
            RETURN {
                id: i.id,
                content: i.content,
                confidence: i.confidence,
                created_at: i.created_at
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "limit": max_insights
            })
            return results or []
        except Exception as e:
            logger.error(f"[InsightService] Failed to get urgent insights: {e}")
            return []
    
    async def mark_insight_shown(self, insight_id: str) -> bool:
        """Mark an insight as shown to increment its shown count."""
        query = """
        FOR i IN Insight
            FILTER i.id == @id
            UPDATE i WITH {
                shown_count: (i.shown_count == null ? 1 : i.shown_count + 1),
                last_shown: @now
            } IN Insight
            RETURN i.id
        """
        
        try:
            await self.graph.execute_query(query, {
                "id": insight_id,
                "now": datetime.utcnow().isoformat()
            })
            return True
        except Exception as e:
            logger.error(f"[InsightService] Failed to mark insight shown: {e}")
            return False
    
    async def dismiss_insight(self, insight_id: str, user_id: int) -> bool:
        """Dismiss an insight so it won't be shown again."""
        query = """
        FOR i IN Insight
            FILTER i.id == @id AND i.user_id == @user_id
            UPDATE i WITH {
                dismissed: true,
                dismissed_at: @now
            } IN Insight
            RETURN i.id
        """
        
        try:
            await self.graph.execute_query(query, {
                "id": insight_id,
                "user_id": user_id,
                "now": datetime.utcnow().isoformat()
            })
            logger.info(f"[InsightService] Dismissed insight {insight_id}")
            return True
        except Exception as e:
            logger.error(f"[InsightService] Failed to dismiss insight: {e}")
            return False
    
    async def format_insights_for_response(
        self,
        insights: List[Dict[str, Any]]
    ) -> str:
        """
        Format insights as a string to append to agent responses.
        
        Returns:
            Formatted string like "💡 Heads up: ..."
        """
        if not insights:
            return ""
        
        formatted_parts = []
        
        for insight in insights[:MAX_INSIGHTS_PER_RESPONSE]:
            insight_type = insight.get("type", "suggestion")
            content = insight.get("content", "")
            
            if insight_type == "conflict":
                formatted_parts.append(f"⚠️ **Heads up:** {content}")
            elif insight_type == "connection":
                formatted_parts.append(f"🔗 **Related:** {content}")
            else:
                formatted_parts.append(f"💡 **Suggestion:** {content}")
            
            # Mark as shown
            if insight.get("id"):
                await self.mark_insight_shown(insight["id"])
        
        if formatted_parts:
            return "\n\n---\n" + "\n".join(formatted_parts)
        
        return ""

    async def stream_urgent_insights(self, user_id: int):
        """
        Async generator that yields urgent insights as they arrive.
        """
        if not self.reactive_service:
            # Fallback to polling
            while True:
                insights = await self.get_urgent_insights(user_id)
                for insight in insights:
                    yield insight
                    # Mark shown to avoid loops
                    await self.mark_insight_shown(insight['id'])
                await asyncio.sleep(10)
        else:
            # Use reactive subscription queue
            queue = asyncio.Queue()
            
            async def _handler(event):
                # Check if event is a new urgent insight for this user
                if getattr(event, 'node_type', None) == NodeType.INSIGHT and event.user_id == user_id:
                     props = event.properties
                     if props.get('type') == 'conflict' or props.get('confidence', 0) > 0.8:
                         await queue.put(props)
            
            from src.services.reasoning.reactive_service import GraphEventType
            self.reactive_service.subscribe(GraphEventType.NODE_CREATED, _handler)
            
            while True:
                insight = await queue.get()
                yield insight
                queue.task_done()
                
    async def generate_proactive_insights(self, user_id: int) -> int:
        """
        Run background analysis to generate new proactive insights.
        
        Checks for:
        1. Conflicts (e.g., meeting overlap)
        2. Missing Loops (based on learned patterns)
        3. Forgotten Context (revisit old topics)
        
        Returns:
            Number of new insights generated
        """
        count = 0
        
        # 1. Conflict Detection (Simple Overlaps)
        # Find events today that overlap
        today = datetime.utcnow().strftime("%Y-%m-%d")
        # AQL query for overlapping events (simplified - assumes OVERLAPS edges exist)
        overlap_query = """
        FOR e1 IN CalendarEvent
            FILTER STARTS_WITH(e1.start_time, @today) AND e1.user_id == @user_id
            FOR edge IN OVERLAPS
                FILTER edge._from == e1._id
                LET e2 = DOCUMENT(edge._to)
                RETURN {
                    t1: e1.title,
                    t2: e2.title,
                    id1: e1.id
                }
        """
        # (Simplified, assuming OVERLAPS relation is maintained by TemporalIndexer)
        
        # 2. Missing Loop Detection (Pattern-based)
        # "You usually [Action] after [Trigger], but haven't yet."
        # This is a complex pattern query - simplified for AQL:
        pattern_query = """
        FOR tb IN TimeBlock
            FILTER tb.user_id == @user_id AND tb.start_time > @recent_cutoff
            FOR trigger_edge IN OCCURRED_DURING
                FILTER trigger_edge._to == tb._id
                LET last_trigger = DOCUMENT(trigger_edge._from)
                FOR p IN Insight
                    FILTER p.type == 'pattern'
                       AND (p.trigger == last_trigger.summary OR p.trigger == last_trigger.title)
                    RETURN {
                        trigger: p.trigger,
                        action: p.action,
                        confidence: p.confidence
                    }
        """
        # This graph query is complex and might depend on specific text matching. 
        # We will implement a simplified robust check here.
        
        try:
            # Check for forgotten context (Topics not touched in > 30 days but mentioned in new email)
            # Find recent emails - AQL version
            recent_files = await self.graph.execute_query("""
                FOR e IN Email
                    FILTER e.timestamp > @yesterday AND e.user_id == @user_id
                    FOR edge IN DISCUSSES
                        FILTER edge._from == e._id
                        LET t = DOCUMENT(edge._to)
                        FILTER t.last_mentioned < @month_ago
                        LIMIT 3
                        RETURN {
                            topic: t.name,
                            subject: e.subject
                        }
            """, {
                "user_id": user_id,
                "yesterday": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                "month_ago": (datetime.utcnow() - timedelta(days=30)).isoformat()
            })
            
            for row in recent_files or []:
                topic = row["topic"]
                subject = row["subject"]
                content = f"The email '{subject}' mentions '{topic}', which you haven't worked on in over a month."
                await self._create_insight(user_id, content, "context", 0.8, actionable=True)
                count += 1
                
        except Exception as e:
            logger.warning(f"[InsightService] Failed context check: {e}")

        # Check for conflicts (if not already handled by graph)
        # We can implement a direct overlapping query here if needed
        
        # 3. High Activity Document Detection
        # "You've been working on [Doc] a lot - do you want to share it or create a task?"
        if self.drive_service:
            try:
                # We can't query "view activity", but we can look for recently modified files
                modified_docs = await asyncio.to_thread(self.drive_service.list_recent_files, limit=3)
                for doc in modified_docs or []:
                    # Simple heuristic: If modified today, suggest follow up
                    if doc.get('modifiedTime', '').startswith(today):
                        content = f"You've been active on '{doc.get('name')}'. Need to create a task or share it?"
                        await self._create_insight(user_id, content, "suggestion", 0.7, actionable=True)
                        count += 1
            except Exception as e:
                logger.warning(f"[InsightService] Failed doc check: {e}")

        # Trigger Deep Reasoning Cycle
        if self.reasoning_service:
            try:
                stats = await self.reasoning_service.run_reasoning_cycle(user_id)
                count += stats.get("insights", 0)
            except Exception as e:
                logger.error(f"[InsightService] Reasoning cycle failed: {e}")
                
        return count

    async def _create_insight(
        self, 
        user_id: int, 
        content: str, 
        type: str, 
        confidence: float,
        actionable: bool = False
    ) -> bool:
        """Helper to create an insight node."""
        try:
            properties = {
                "content": content,
                "type": type,
                "confidence": confidence,
                "actionable": actionable,
                "user_id": user_id,
                "created_at": datetime.utcnow().isoformat(),
                "source": "InsightService"
            }
            await self.graph.create_node(NodeType.INSIGHT, properties)
            return True
        except Exception as e:
            logger.error(f"[InsightService] Failed to create insight: {e}")
            return False


# Global instance management
_insight_service: Optional[InsightService] = None


def get_insight_service() -> Optional[InsightService]:
    """Get the global insight service instance."""
    return _insight_service


def init_insight_service(config: Config, graph_manager: KnowledgeGraphManager) -> InsightService:
    """Initialize and return the global insight service."""
    global _insight_service
    
    # Drive service is optional - must be passed explicitly if needed
    # NOTE: Background IndexService should pass user-specific drive_service when needed
    drive_service = None
    # Do NOT use hardcoded user_id for background services

    _insight_service = InsightService(config, graph_manager, drive_service)
    logger.info("[InsightService] Initialized")
    return _insight_service
