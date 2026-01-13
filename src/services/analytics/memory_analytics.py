"""
Memory Graph Analytics Service

Advanced graph analytics for the memory system, providing:
- Relationship pattern analysis
- Communication frequency trends
- Topic evolution tracking
- Cross-app activity insights
- Meeting preparation metrics

"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum

from src.services.indexing.graph import KnowledgeGraphManager
from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class AnalyticsMetric(str, Enum):
    """Available analytics metrics"""
    RELATIONSHIP_STRENGTH = "relationship_strength"
    COMMUNICATION_FREQUENCY = "communication_frequency"
    TOPIC_ACTIVITY = "topic_activity"
    APP_USAGE_DISTRIBUTION = "app_usage_distribution"
    TEMPORAL_PATTERNS = "temporal_patterns"
    NETWORK_CENTRALITY = "network_centrality"


class MemoryGraphAnalytics:
    """
    Advanced analytics for the memory graph.
    
    Provides insights into:
    - Who you communicate with most
    - Which topics are trending
    - Communication patterns over time
    - Cross-app activity distribution
    """
    
    def __init__(
        self,
        config: Config,
        graph_manager: KnowledgeGraphManager,
        llm_client=None
    ):
        self.config = config
        self.graph_manager = graph_manager
        self.llm_client = llm_client
    
    async def get_relationship_analytics(
        self,
        user_id: int,
        time_range_days: int = 30,
        top_n: int = 10
    ) -> Dict[str, Any]:
        """
        Analyze relationship patterns and communication strength.
        
        Returns:
        - Top contacts by interaction count
        - Relationship strength distribution
        - New connections vs established relationships
        - Communication trends (increasing/decreasing)
        """
        result = {
            "top_contacts": [],
            "strength_distribution": {},
            "new_connections": [],
            "trends": {},
            "generated_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Get top contacts by interaction frequency - AQL version
            top_contacts_query = """
            FOR p IN Person
                FOR content IN UNION(
                    (FOR e IN Email FILTER e.user_id == @user_id RETURN e),
                    (FOR m IN Message FILTER m.user_id == @user_id RETURN m)
                )
                    FOR edge IN UNION(
                        (FOR e IN SENT FILTER e._from == p._id AND e._to == content._id RETURN e),
                        (FOR e IN RECEIVED FILTER e._from == content._id AND e._to == p._id RETURN e),
                        (FOR e IN MENTIONS FILTER (e._from == content._id AND e._to == p._id) OR (e._from == p._id AND e._to == content._id) RETURN e)
                    )
                        FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                        COLLECT person = p
                        AGGREGATE interactions = LENGTH(1), last_int = MAX(content.timestamp)
                        SORT interactions DESC
                        LIMIT @top_n
                        RETURN {
                            name: person.name,
                            email: person.email,
                            interactions: interactions,
                            last_interaction: last_int,
                            strength: person.relationship_strength
                        }
            """
            
            contacts = await self.graph_manager.execute_query(top_contacts_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D',
                'top_n': top_n
            })
            
            for contact in contacts or []:
                result["top_contacts"].append({
                    "name": contact.get('name', 'Unknown'),
                    "email": contact.get('email'),
                    "interactions": contact.get('interactions', 0),
                    "last_interaction": str(contact.get('last_interaction')),
                    "strength": contact.get('strength', 0.5)
                })
            
            # Get strength distribution - AQL version
            strength_query = """
            FOR r IN COMMUNICATES_WITH
                LET p1 = DOCUMENT(r._from)
                FILTER p1.user_id == @user_id
                LET category = (
                    r.strength >= 0.8 ? 'strong' :
                    r.strength >= 0.5 ? 'moderate' :
                    r.strength >= 0.3 ? 'weak' : 'minimal'
                )
                COLLECT cat = category WITH COUNT INTO cnt
                RETURN { category: cat, count: cnt }
            """
            
            distribution = await self.graph_manager.execute_query(strength_query, {
                'user_id': user_id
            })
            
            for row in distribution or []:
                result["strength_distribution"][row.get('category', 'unknown')] = row.get('count', 0)
            
            # Find new connections (first interaction in last 7 days) - AQL version
            new_query = """
            FOR p IN Person
                FOR edge IN UNION(
                    (FOR e IN SENT FILTER e._from == p._id RETURN e),
                    (FOR e IN RECEIVED FILTER e._to == p._id RETURN e)
                )
                    LET content = DOCUMENT(edge._from == p._id ? edge._to : edge._from)
                    FILTER content.user_id == @user_id
                       AND content.timestamp >= DATE_SUBTRACT(DATE_NOW(), 7, 'day')
                    COLLECT person = p
                    AGGREGATE first_int = MIN(content.timestamp), total = LENGTH(1)
                    FILTER first_int >= DATE_SUBTRACT(DATE_NOW(), 7, 'day')
                    SORT first_int DESC
                    LIMIT 5
                    RETURN {
                        name: person.name,
                        email: person.email,
                        first_interaction: first_int,
                        interactions: total
                    }
            """
            
            new_connections = await self.graph_manager.execute_query(new_query, {
                'user_id': user_id
            })
            
            for conn in new_connections or []:
                result["new_connections"].append({
                    "name": conn.get('name', 'Unknown'),
                    "email": conn.get('email'),
                    "first_interaction": str(conn.get('first_interaction')),
                    "total_interactions": conn.get('interactions', 1)
                })
            
        except Exception as e:
            logger.error(f"[MemoryAnalytics] Relationship analysis failed: {e}")
        
        return result
    
    async def get_topic_analytics(
        self,
        user_id: int,
        time_range_days: int = 30,
        top_n: int = 15
    ) -> Dict[str, Any]:
        """
        Analyze topic trends and evolution.
        
        Returns:
        - Trending topics (high recent activity)
        - Topic clusters
        - Topic velocity (growth rate)
        - Cross-app topic distribution
        """
        result = {
            "trending_topics": [],
            "topic_clusters": [],
            "topic_sources": {},
            "weekly_activity": [],
            "generated_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Get trending topics - AQL version
            trending_query = """
            FOR t IN Topic
                FILTER t.user_id == @user_id
                FOR edge IN DISCUSSES
                    FILTER edge._to == t._id
                    LET content = DOCUMENT(edge._from)
                    FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                    COLLECT topic = t
                    AGGREGATE mentions = LENGTH(1), last_mentioned = MAX(content.timestamp)
                    SORT mentions DESC
                    LIMIT @top_n
                    RETURN {
                        topic: topic.name,
                        topic_id: topic.id,
                        mentions: mentions,
                        last_mentioned: last_mentioned,
                        first_seen: topic.created_at
                    }
            """
            
            topics = await self.graph_manager.execute_query(trending_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D',
                'top_n': top_n
            })
            
            for topic in topics or []:
                # Calculate velocity (mentions per day since first seen)
                first_seen = topic.get('first_seen')
                mentions = topic.get('mentions', 0)
                velocity = 0
                
                if first_seen:
                    try:
                        first_dt = datetime.fromisoformat(str(first_seen).replace('Z', '+00:00'))
                        days_active = max((datetime.now() - first_dt.replace(tzinfo=None)).days, 1)
                        velocity = mentions / days_active
                    except:
                        pass
                
                result["trending_topics"].append({
                    "name": topic.get('topic', 'Unknown'),
                    "id": topic.get('topic_id'),
                    "mentions": mentions,
                    "velocity": round(velocity, 2),
                    "last_mentioned": str(topic.get('last_mentioned'))
                })
            
            # Get topic clusters (related topics) - AQL version
            cluster_query = """
            FOR t1 IN Topic
                FILTER t1.user_id == @user_id
                LET related = (
                    FOR edge IN RELATED_TO
                        FILTER edge._from == t1._id OR edge._to == t1._id
                        LET t2 = edge._from == t1._id ? DOCUMENT(edge._to) : DOCUMENT(edge._from)
                        FILTER t2.node_type == 'Topic'
                        LIMIT 5
                        RETURN DISTINCT t2.name
                )
                FILTER LENGTH(related) > 0
                LIMIT 10
                RETURN {
                    topic: t1.name,
                    related: related
                }
            """
            
            clusters = await self.graph_manager.execute_query(cluster_query, {
                'user_id': user_id
            })
            
            for cluster in clusters or []:
                result["topic_clusters"].append({
                    "topic": cluster.get('topic'),
                    "related": cluster.get('related', [])
                })
            
            # Get topic by source breakdown - AQL version
            source_query = """
            FOR t IN Topic
                FILTER t.user_id == @user_id
                FOR edge IN DISCUSSES
                    FILTER edge._to == t._id
                    LET content = DOCUMENT(edge._from)
                    FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                    COLLECT source = content.source
                    AGGREGATE topics = COUNT_DISTINCT(t), mentions = LENGTH(1)
                    SORT mentions DESC
                    RETURN {
                        source: source,
                        topics: topics,
                        mentions: mentions
                    }
            """
            
            sources = await self.graph_manager.execute_query(source_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D'
            })
            
            for source in sources or []:
                result["topic_sources"][source.get('source', 'unknown')] = {
                    "topics": source.get('topics', 0),
                    "mentions": source.get('mentions', 0)
                }
            
        except Exception as e:
            logger.error(f"[MemoryAnalytics] Topic analysis failed: {e}")
        
        return result
    
    async def get_temporal_activity_patterns(
        self,
        user_id: int,
        time_range_days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze activity patterns over time.
        
        Returns:
        - Activity by day of week
        - Activity by hour of day
        - Busy vs quiet periods
        - Activity trends
        """
        result = {
            "daily_pattern": {},
            "weekly_pattern": {},
            "activity_trend": [],
            "peak_hours": [],
            "quiet_periods": [],
            "generated_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Activity by day of week - AQL version
            weekly_query = """
            FOR edge IN UNION(
                (FOR e IN OCCURRED_DURING RETURN e),
                (FOR e IN SCHEDULED_FOR RETURN e)
            )
                LET tb = DOCUMENT(edge._to)
                LET content = DOCUMENT(edge._from)
                FILTER content.user_id == @user_id
                   AND tb.date >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                COLLECT day = DATE_DAYOFWEEK(tb.date)
                AGGREGATE activity = LENGTH(1)
                RETURN { day: day, activity: activity }
            """
            
            weekly = await self.graph_manager.execute_query(weekly_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D'
            })
            
            day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            for row in weekly or []:
                day_num = row.get('day', 0)
                day_name = day_names[day_num] if 0 <= day_num < 7 else f"Day {day_num}"
                result["weekly_pattern"][day_name] = row.get('activity', 0)
            
            # Activity by hour (approximate from timestamps) - AQL version
            hourly_query = """
            FOR content IN UNION(
                (FOR e IN Email FILTER e.user_id == @user_id AND e.timestamp != null RETURN e),
                (FOR m IN Message FILTER m.user_id == @user_id AND m.timestamp != null RETURN m),
                (FOR c IN CalendarEvent FILTER c.user_id == @user_id AND c.timestamp != null RETURN c)
            )
                FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                COLLECT hour = DATE_HOUR(content.timestamp)
                AGGREGATE activity = LENGTH(1)
                SORT hour
                RETURN { hour: hour, activity: activity }
            """
            
            hourly = await self.graph_manager.execute_query(hourly_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D'
            })
            
            hourly_data = {}
            for row in hourly or []:
                hour = row.get('hour', 0)
                hourly_data[f"{hour:02d}:00"] = row.get('activity', 0)
            result["daily_pattern"] = hourly_data
            
            # Find peak hours (top 3)
            if hourly_data:
                sorted_hours = sorted(hourly_data.items(), key=lambda x: x[1], reverse=True)
                result["peak_hours"] = [h for h, _ in sorted_hours[:3]]
                result["quiet_periods"] = [h for h, _ in sorted_hours[-3:]]
            
            # Activity trend (daily counts for last 14 days) - AQL version
            trend_query = """
            FOR content IN UNION(
                (FOR e IN Email FILTER e.user_id == @user_id AND e.timestamp != null RETURN e),
                (FOR m IN Message FILTER m.user_id == @user_id AND m.timestamp != null RETURN m),
                (FOR c IN CalendarEvent FILTER c.user_id == @user_id AND c.timestamp != null RETURN c)
            )
                FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), 14, 'day')
                COLLECT day = DATE_TRUNC(content.timestamp, 'day')
                AGGREGATE activity = LENGTH(1)
                SORT day DESC
                LIMIT 14
                RETURN { day: day, activity: activity }
            """
            
            trend = await self.graph_manager.execute_query(trend_query, {
                'user_id': user_id
            })
            
            for row in trend or []:
                result["activity_trend"].append({
                    "date": str(row.get('day')),
                    "activity": row.get('activity', 0)
                })
            
        except Exception as e:
            logger.error(f"[MemoryAnalytics] Temporal analysis failed: {e}")
        
        return result
    
    async def get_cross_app_insights(
        self,
        user_id: int,
        time_range_days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze cross-app activity and connections.
        
        Returns:
        - Content distribution by source
        - Cross-app relationship linking
        - Integration coverage
        - Entity unification statistics
        """
        result = {
            "source_distribution": {},
            "cross_app_connections": [],
            "unification_stats": {},
            "integration_health": {},
            "generated_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Content by source - AQL version
            source_query = """
            FOR content IN UNION(
                (FOR e IN Email FILTER e.user_id == @user_id RETURN e),
                (FOR m IN Message FILTER m.user_id == @user_id RETURN m),
                (FOR c IN CalendarEvent FILTER c.user_id == @user_id RETURN c),
                (FOR d IN Document FILTER d.user_id == @user_id RETURN d)
            )
                FILTER content.timestamp >= DATE_SUBTRACT(DATE_NOW(), @days, 'day')
                COLLECT source = content.source, type = content.node_type
                AGGREGATE cnt = LENGTH(1)
                SORT cnt DESC
                RETURN { source: source, type: type, count: cnt }
            """
            
            sources = await self.graph_manager.execute_query(source_query, {
                'user_id': user_id,
                'duration': f'P{time_range_days}D'
            })
            
            for row in sources or []:
                source = row.get('source', 'unknown')
                if source not in result["source_distribution"]:
                    result["source_distribution"][source] = {}
                result["source_distribution"][source][row.get('type', 'Unknown')] = row.get('count', 0)
            
            # Cross-app connections (Person mentioned in multiple apps) - AQL version
            cross_app_query = """
            FOR p IN Person
                FOR edge IN UNION(
                    (FOR e IN SENT FILTER e._from == p._id RETURN e),
                    (FOR e IN RECEIVED FILTER e._to == p._id RETURN e),
                    (FOR e IN MENTIONS FILTER e._from == p._id OR e._to == p._id RETURN e)
                )
                    LET content = DOCUMENT(edge._from == p._id ? edge._to : edge._from)
                    FILTER content.user_id == @user_id
                    COLLECT person = p
                    AGGREGATE sources = COLLECT_SET(content.source)
                    FILTER LENGTH(sources) > 1
                    SORT LENGTH(sources) DESC
                    LIMIT 10
                    RETURN {
                        name: person.name,
                        email: person.email,
                        sources: sources,
                        app_count: LENGTH(sources)
                    }
            """
            
            cross_app = await self.graph_manager.execute_query(cross_app_query, {
                'user_id': user_id
            })
            
            for row in cross_app or []:
                result["cross_app_connections"].append({
                    "name": row.get('name', 'Unknown'),
                    "email": row.get('email'),
                    "sources": row.get('sources', []),
                    "app_count": row.get('app_count', 0)
                })
            
            # Entity unification stats - AQL version
            unification_query = """
            FOR edge IN SAME_AS
                LET p = DOCUMENT(edge._from)
                LET unified = DOCUMENT(edge._to)
                FILTER p.user_id == @user_id
                COLLECT
                AGGREGATE merged = COUNT_DISTINCT(p), unique = COUNT_DISTINCT(unified)
                RETURN {
                    merged_identities: merged,
                    unique_persons: unique
                }
            """
            
            unification = await self.graph_manager.execute_query(unification_query, {
                'user_id': user_id
            })
            
            if unification:
                result["unification_stats"] = {
                    "merged_identities": unification[0].get('merged_identities', 0),
                    "unique_persons": unification[0].get('unique_persons', 0)
                }
            
            # Integration health (recent activity per source) - AQL version
            health_query = """
            FOR content IN UNION(
                (FOR e IN Email FILTER e.user_id == @user_id AND e.timestamp >= DATE_SUBTRACT(DATE_NOW(), 7, 'day') RETURN e),
                (FOR m IN Message FILTER m.user_id == @user_id AND m.timestamp >= DATE_SUBTRACT(DATE_NOW(), 7, 'day') RETURN m),
                (FOR c IN CalendarEvent FILTER c.user_id == @user_id AND c.timestamp >= DATE_SUBTRACT(DATE_NOW(), 7, 'day') RETURN c),
                (FOR d IN Document FILTER d.user_id == @user_id AND d.timestamp >= DATE_SUBTRACT(DATE_NOW(), 7, 'day') RETURN d)
            )
                COLLECT source = content.source
                AGGREGATE last_activity = MAX(content.timestamp), weekly_count = LENGTH(1)
                RETURN {
                    source: source,
                    last_activity: last_activity,
                    weekly_count: weekly_count
                }
            """
            
            health = await self.graph_manager.execute_query(health_query, {
                'user_id': user_id
            })
            
            for row in health or []:
                source = row.get('source', 'unknown')
                last_activity = row.get('last_activity')
                hours_ago = 0
                if last_activity:
                    try:
                        last_dt = datetime.fromisoformat(str(last_activity).replace('Z', '+00:00'))
                        hours_ago = int((datetime.now() - last_dt.replace(tzinfo=None)).total_seconds() / 3600)
                    except:
                        pass
                
                status = "healthy" if hours_ago < 24 else "stale" if hours_ago < 168 else "inactive"
                
                result["integration_health"][source] = {
                    "status": status,
                    "last_activity_hours_ago": hours_ago,
                    "weekly_count": row.get('weekly_count', 0)
                }
            
        except Exception as e:
            logger.error(f"[MemoryAnalytics] Cross-app analysis failed: {e}")
        
        return result
    
    async def get_full_analytics_report(
        self,
        user_id: int,
        time_range_days: int = 30
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive analytics report.
        
        Combines all analytics into a single report.
        """
        return {
            "relationships": await self.get_relationship_analytics(user_id, time_range_days),
            "topics": await self.get_topic_analytics(user_id, time_range_days),
            "temporal": await self.get_temporal_activity_patterns(user_id, time_range_days),
            "cross_app": await self.get_cross_app_insights(user_id, time_range_days),
            "generated_at": datetime.utcnow().isoformat(),
            "time_range_days": time_range_days
        }


# Global instance management
_memory_analytics: Optional[MemoryGraphAnalytics] = None


def get_memory_analytics() -> Optional[MemoryGraphAnalytics]:
    """Get the global memory analytics instance."""
    return _memory_analytics


def init_memory_analytics(
    config: Config,
    graph_manager: KnowledgeGraphManager,
    llm_client=None
) -> MemoryGraphAnalytics:
    """Initialize and return the global memory analytics service."""
    global _memory_analytics
    _memory_analytics = MemoryGraphAnalytics(
        config=config,
        graph_manager=graph_manager,
        llm_client=llm_client
    )
    logger.info("[MemoryAnalytics] Service initialized")
    return _memory_analytics
