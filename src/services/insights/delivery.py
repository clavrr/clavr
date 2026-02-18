"""
Insight Delivery Service

Responsible for delivering proactive insights to users. Works with the
GraphObserverService which generates insights, and this service:
1. Scores insights by urgency and relevance
2. Filters for user-specific delivery
3. Delivers via appropriate channels (push, in-app, digest)
4. Tracks delivery and engagement

This makes the memory graph "living" - not just storing insights, but
actively surfacing them to help users:
- See what they'd miss alone
- Learn more deeply
- Take action with clarity

Version: 1.0.0
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)


class InsightPriority(str, Enum):
    """Priority levels for insight delivery."""
    URGENT = "urgent"      # Deliver immediately (conflicts, warnings)
    HIGH = "high"          # Deliver within the hour
    MEDIUM = "medium"      # Include in next digest
    LOW = "low"            # Store for context, don't push


class DeliveryChannel(str, Enum):
    """Available channels for insight delivery."""
    PUSH = "push"          # Push notification
    IN_APP = "in_app"      # In-app notification
    EMAIL_DIGEST = "email_digest"  # Daily/weekly email digest
    CHAT = "chat"          # Show in chat interface


class InsightDeliveryService:
    """
    Service for delivering insights to users proactively.
    
    Responsibilities:
    1. Query undelivered insights from the graph
    2. Score and prioritize insights for each user
    3. Deliver via appropriate channels
    4. Track delivery status and user engagement
    """
    
    # Scoring weights for insight prioritization
    PRIORITY_WEIGHTS = {
        "conflict": 1.0,    # Highest priority
        "warning": 0.9,
        "connection": 0.6,
        "suggestion": 0.5,
        "info": 0.3,
    }
    
    # Confidence threshold for delivery
    MIN_DELIVERY_CONFIDENCE = 0.6
    
    # Time-sensitivity boost (insights about events happening soon)
    TIME_SENSITIVITY_BOOST = 0.3
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.is_running = False
        self._stop_event = asyncio.Event()
        
    async def start(self):
        """Start the insight delivery loop."""
        if self.is_running:
            return
            
        self.is_running = True
        self._stop_event.clear()
        
        logger.info("[InsightDelivery] Service started")
        asyncio.create_task(self._run_loop())
        
    async def stop(self):
        """Stop the service."""
        self.is_running = False
        self._stop_event.set()
        logger.info("[InsightDelivery] Service stopped")
        
    async def _run_loop(self):
        """Main delivery loop - check for insights to deliver."""
        while self.is_running:
            try:
                # Run check every 5 minutes
                await self.check_and_deliver_all_users()
                
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    pass
                    
            except Exception as e:
                logger.error(f"[InsightDelivery] Error in loop: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def check_and_deliver_all_users(self) -> Dict[str, int]:
        """
        Check for undelivered insights for all users and deliver them.
        
        Returns:
            Stats on insights processed and delivered
        """
        stats = {"processed": 0, "delivered": 0, "skipped": 0}
        
        # Get all users with undelivered insights - AQL version
        query = """
        FOR i IN Insight
            FILTER i.delivered == null OR i.delivered == false
            RETURN DISTINCT i.user_id
        """
        
        try:
            users = await self.graph.execute_query(query)
            
            for user_record in (users or []):
                user_id = user_record.get("user_id")
                if user_id:
                    user_stats = await self.check_and_deliver(user_id)
                    stats["processed"] += user_stats.get("processed", 0)
                    stats["delivered"] += user_stats.get("delivered", 0)
                    stats["skipped"] += user_stats.get("skipped", 0)
                    
        except Exception as e:
            logger.error(f"[InsightDelivery] Error getting users: {e}")
            
        return stats
    
    async def check_and_deliver(self, user_id: int) -> Dict[str, int]:
        """
        Check for undelivered insights for a specific user.
        
        Args:
            user_id: User to check insights for
            
        Returns:
            Stats on insights processed
        """
        stats = {"processed": 0, "delivered": 0, "skipped": 0}
        
        # Get undelivered insights for user
        insights = await self._get_pending_insights(user_id)
        stats["processed"] = len(insights)
        
        if not insights:
            return stats
        
        # Score and prioritize
        scored = self._score_for_delivery(insights)
        
        # Get top insights (limit to 3 per check to avoid notification fatigue)
        for insight in scored[:3]:
            priority = self._determine_priority(insight)
            
            if priority in [InsightPriority.URGENT, InsightPriority.HIGH]:
                delivered = await self._deliver(user_id, insight, priority)
                if delivered:
                    stats["delivered"] += 1
                else:
                    stats["skipped"] += 1
            else:
                # Queue for digest
                await self._queue_for_digest(user_id, insight)
                stats["skipped"] += 1
                
        return stats
    
    async def _get_pending_insights(self, user_id: int) -> List[Dict[str, Any]]:
        """Get undelivered insights for a user, ordered by recency."""
        query = """
        FOR i IN Insight
            FILTER (i.user_id == @user_id OR i.user_id == null)
               AND (i.delivered == null OR i.delivered == false)
               AND i.confidence >= @min_confidence
            
            LET related_entities = (
                FOR edge IN ABOUT
                    FILTER edge._from == i._id
                    LET related = DOCUMENT(edge._to)
                    RETURN DISTINCT {
                        id: related.id,
                        type: related.node_type,
                        name: related.name
                    }
            )
            
            SORT i.created_at DESC
            LIMIT 20
            
            RETURN {
                id: i.id,
                content: i.content,
                type: i.type,
                confidence: i.confidence,
                created_at: i.created_at,
                actionable: i.actionable,
                related_entities: related_entities
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "min_confidence": self.MIN_DELIVERY_CONFIDENCE,
            })
            return results or []
        except Exception as e:
            logger.error(f"[InsightDelivery] Error getting insights: {e}")
            return []
    
    def _score_for_delivery(self, insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Score insights for delivery priority.
        
        Scoring based on:
        - Type weight (conflicts higher than suggestions)
        - Confidence score
        - Recency
        - Time sensitivity (related to upcoming events)
        - Actionability
        """
        scored = []
        now = datetime.utcnow()
        
        for insight in insights:
            base_score = 0.0
            
            # Type weight
            insight_type = insight.get("type", "info")
            base_score += self.PRIORITY_WEIGHTS.get(insight_type, 0.3)
            
            # Confidence boost
            confidence = insight.get("confidence", 0.5)
            base_score += confidence * 0.3
            
            # Recency boost (insights from last hour get boost)
            created_at = insight.get("created_at")
            if created_at:
                try:
                    if isinstance(created_at, str):
                        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        created = created_at
                    age_hours = (now - created.replace(tzinfo=None)).total_seconds() / 3600
                    if age_hours < 1:
                        base_score += 0.2
                    elif age_hours < 24:
                        base_score += 0.1
                except Exception:
                    pass
            
            # Actionability boost
            if insight.get("actionable"):
                base_score += 0.15
            
            insight["delivery_score"] = min(base_score, 1.0)
            scored.append(insight)
        
        # Sort by score descending
        scored.sort(key=lambda x: x.get("delivery_score", 0), reverse=True)
        return scored
    
    def _determine_priority(self, insight: Dict[str, Any]) -> InsightPriority:
        """Determine the delivery priority for an insight."""
        score = insight.get("delivery_score", 0)
        insight_type = insight.get("type", "info")
        
        if insight_type == "conflict" or score >= 0.9:
            return InsightPriority.URGENT
        elif insight_type == "warning" or score >= 0.7:
            return InsightPriority.HIGH
        elif score >= 0.5:
            return InsightPriority.MEDIUM
        else:
            return InsightPriority.LOW
    
    async def _deliver(
        self, 
        user_id: int, 
        insight: Dict[str, Any],
        priority: InsightPriority
    ) -> bool:
        """
        Deliver an insight to the user.
        
        Currently logs delivery - actual implementation would:
        - Push notification for urgent/high
        - In-app notification
        - Store in user's notification queue
        """
        try:
            insight_id = insight.get("id")
            content = insight.get("content", "")
            insight_type = insight.get("type", "info")
            
            logger.info(f"[InsightDelivery] Delivering to user {user_id}: "
                       f"[{priority.value}] {insight_type}: {content[:100]}...")
            
            # Mark as delivered in graph - AQL version
            update_query = """
            FOR i IN Insight
                FILTER i.id == @id
                UPDATE i WITH {
                    delivered: true,
                    delivered_at: @now,
                    delivery_channel: @channel,
                    delivery_priority: @priority
                } IN Insight
            """
            
            await self.graph.execute_query(update_query, {
                "id": insight_id,
                "now": datetime.utcnow().isoformat(),
                "channel": DeliveryChannel.IN_APP.value,
                "priority": priority.value,
            })
            
            # === DELIVERY IMPLEMENTATION ===
            
            # 1. WebSocket for in-app real-time notifications
            await self._deliver_via_websocket(user_id, insight, priority)
            
            # 2. Push notification for urgent/high priority insights
            if priority in (InsightPriority.URGENT, InsightPriority.HIGH):
                await self._deliver_via_push(user_id, insight, priority)
            
            # 3. Email notification for urgent insights only
            if priority == InsightPriority.URGENT:
                await self._deliver_via_email(user_id, insight, priority)
            
            # 4. Queue medium priority for digest delivery
            elif priority == InsightPriority.MEDIUM:
                await self._queue_for_digest(user_id, insight)
            
            return True
            
        except Exception as e:
            logger.error(f"[InsightDelivery] Failed to deliver insight: {e}")
            return False
    
    async def _deliver_via_websocket(
        self, 
        user_id: int, 
        insight: Dict[str, Any],
        priority: InsightPriority
    ) -> None:
        """
        Deliver insight via WebSocket for real-time in-app notifications.
        
        Integrates with the ConnectionManager if available.
        """
        try:
            from api.dependencies import AppState
            connection_manager = AppState.get_connection_manager()
            
            if connection_manager:
                notification_payload = {
                    "type": "insight_notification",
                    "priority": priority.value,
                    "insight": {
                        "id": insight.get("id"),
                        "content": insight.get("content"),
                        "insight_type": insight.get("type"),
                        "confidence": insight.get("confidence"),
                        "actionable": insight.get("actionable", False),
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await connection_manager.send_to_user(user_id, notification_payload)
                logger.debug(f"[InsightDelivery] WebSocket notification sent to user {user_id}")
            else:
                logger.debug("[InsightDelivery] No WebSocket connection manager available")
                
        except ImportError:
            logger.debug("[InsightDelivery] WebSocket dependencies not available")
        except Exception as e:
            logger.warning(f"[InsightDelivery] WebSocket delivery failed: {e}")
    
    async def _deliver_via_push(
        self,
        user_id: int,
        insight: Dict[str, Any],
        priority: InsightPriority
    ) -> bool:
        """
        Deliver insight via push notification to mobile devices.
        
        Integrates with PushNotificationService for Firebase Cloud Messaging.
        """
        try:
            from src.services.notifications.push_service import get_push_service, init_push_service
            
            # Get or initialize push service
            push_service = get_push_service()
            if not push_service:
                push_service = init_push_service(self.config)
            
            if not push_service or not push_service.is_available:
                logger.debug("[InsightDelivery] Push service not available")
                return False
            
            # Send the notification
            success = await push_service.send_insight_notification(
                user_id=user_id,
                insight=insight,
                priority="high" if priority == InsightPriority.URGENT else "normal"
            )
            
            if success:
                logger.info(f"[InsightDelivery] Push notification sent to user {user_id}")
            
            return success
            
        except ImportError:
            logger.debug("[InsightDelivery] Push notification dependencies not available")
            return False
        except Exception as e:
            logger.warning(f"[InsightDelivery] Push delivery failed: {e}")
            return False
    
    async def _deliver_via_email(
        self,
        user_id: int,
        insight: Dict[str, Any],
        priority: InsightPriority
    ) -> None:
        """
        Deliver urgent insights via email notification.
        
        Uses the existing Celery notification tasks infrastructure.
        """
        try:
            from src.database import get_db_context
            from src.database.models import User
            from src.workers.tasks.notification_tasks import send_email_notification
            
            # Get user email
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if not user or not user.email:
                    logger.warning(f"[InsightDelivery] No email for user {user_id}")
                    return
                user_email = user.email
            
            # Build email content based on insight type
            insight_type = insight.get("type", "suggestion")
            content = insight.get("content", "")
            
            type_emoji = {
                "conflict": "⚠️",
                "warning": "🚨", 
                "connection": "🔗",
                "suggestion": "💡",
            }
            emoji = type_emoji.get(insight_type, "📌")
            
            subject = f"{emoji} Clavr Insight: {insight_type.capitalize()}"
            message = f"""
{emoji} {insight_type.upper()} INSIGHT

{content}

---
Priority: {priority.value}
This insight was generated by Clavr's proactive assistant.
"""
            
            # Queue email notification via Celery
            send_email_notification.delay(
                user_email=user_email,
                subject=subject,
                message=message,
                template='insight_notification'
            )
            
            logger.info(f"[InsightDelivery] Email notification queued for user {user_id}")
            
        except ImportError as e:
            logger.debug(f"[InsightDelivery] Email dependencies not available: {e}")
        except Exception as e:
            logger.warning(f"[InsightDelivery] Email delivery failed: {e}")
    
    async def _queue_for_digest(self, user_id: int, insight: Dict[str, Any]) -> None:
        """Queue an insight for email digest delivery."""
        try:
            insight_id = insight.get("id")
            
            update_query = """
            FOR i IN Insight
                FILTER i.id == @id
                UPDATE i WITH {
                    queued_for_digest: true,
                    queued_at: @now
                } IN Insight
            """
            
            await self.graph.execute_query(update_query, {
                "id": insight_id,
                "now": datetime.utcnow().isoformat(),
            })
            
        except Exception as e:
            logger.error(f"[InsightDelivery] Failed to queue insight: {e}")
    
    async def get_user_insights(
        self, 
        user_id: int, 
        include_delivered: bool = False,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get insights for a user (for display in UI).
        
        Args:
            user_id: User ID
            include_delivered: Include already delivered insights
            limit: Maximum number to return
        """
        delivered_filter = "" if include_delivered else "AND (i.delivered == null OR i.delivered == false)"
        
        query = f"""
        FOR i IN Insight
            FILTER (i.user_id == @user_id OR i.user_id == null)
               {delivered_filter}
            
            LET related = (
                FOR edge IN ABOUT
                    FILTER edge._from == i._id
                    LET r = DOCUMENT(edge._to)
                    RETURN DISTINCT {{ id: r.id, type: r.node_type }}
            )
            
            SORT i.created_at DESC
            LIMIT @limit
            
            RETURN {{
                id: i.id,
                content: i.content,
                type: i.type,
                confidence: i.confidence,
                created_at: i.created_at,
                actionable: i.actionable,
                delivered: i.delivered,
                related: related
            }}
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "limit": limit,
            })
            return results or []
        except Exception as e:
            logger.error(f"[InsightDelivery] Failed to get user insights: {e}")
            return []
    
    async def mark_insight_read(self, insight_id: str, user_id: int) -> bool:
        """Mark an insight as read by the user (for engagement tracking)."""
        try:
            query = """
            FOR i IN Insight
                FILTER i.id == @id
                UPDATE i WITH {
                    read: true,
                    read_at: @now,
                    read_by_user_id: @user_id
                } IN Insight
            """
            
            await self.graph.execute_query(query, {
                "id": insight_id,
                "now": datetime.utcnow().isoformat(),
                "user_id": user_id,
            })
            return True
        except Exception:
            return False
    
    async def mark_insight_actioned(
        self, 
        insight_id: str, 
        user_id: int,
        action_taken: str
    ) -> bool:
        """Record that the user took action on an insight."""
        try:
            query = """
            FOR i IN Insight
                FILTER i.id == @id
                UPDATE i WITH {
                    actioned: true,
                    actioned_at: @now,
                    action_taken: @action
                } IN Insight
            """
            
            await self.graph.execute_query(query, {
                "id": insight_id,
                "now": datetime.utcnow().isoformat(),
                "action": action_taken,
            })
            return True
        except Exception:
            return False
