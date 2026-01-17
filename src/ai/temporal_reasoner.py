"""
Temporal Reasoner

Advanced temporal reasoning for time-based queries and timeline generation.
Enables agents to understand queries like "What happened last Tuesday?" or "Show me the context around my meeting".
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import re
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

@dataclass
class TemporalContext:
    time_range: Dict[str, datetime]  # start, end
    activities: List[Dict[str, Any]]
    summary: str
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class TimelineEvent:
    event_id: int
    timestamp: datetime
    event_type: str
    summary: str
    related_people: List[str]
    source: str

class TemporalReasoner:
    """
    Advanced reasoning for time-based queries.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        
    async def reason_about_time(self, query: str, user_id: int) -> Optional[TemporalContext]:
        """
        Parse temporal expressions and gather context for a time-based query.
        """
        # 1. Extract temporal intent (simple regex for now, could be LLM-based)
        time_refs = self._parse_temporal_references(query)
        if not time_refs:
            return None
            
        # 2. Resolve to actual time ranges
        time_range = self._resolve_time_range(time_refs)
        if not time_range:
            return None
            
        # 3. Gather activity in those ranges
        activities = await self._gather_temporal_activities(time_range, user_id)
        
        # 4. Generate summary
        summary = self._generate_temporal_summary(activities, time_range)
        
        return TemporalContext(
            time_range=time_range,
            activities=activities,
            summary=summary
        )

    def _parse_temporal_references(self, query: str) -> Optional[str]:
        """
        Extract simple temporal keywords like "yesterday", "last week", "today".
        """
        query_lower = query.lower()
        if "yesterday" in query_lower:
            return "yesterday"
        elif "today" in query_lower:
            return "today"
        elif "last week" in query_lower:
            return "last_week"
        elif "last tuesday" in query_lower: # Example specific day
             return "last_tuesday" # Placeholder for more complex parsing
        return None

    def _resolve_time_range(self, time_ref: str) -> Dict[str, datetime]:
        """
        Convert keyword to start/end datetime.
        """
        now = datetime.now()
        start = now
        end = now
        
        if time_ref == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif time_ref == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59)
        elif time_ref == "last_week":
            start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0)
            end = now
            
        return {"start": start, "end": end}

    async def _gather_temporal_activities(self, time_range: Dict[str, datetime], user_id: int) -> List[Dict[str, Any]]:
        """
        Query the graph for events within the time range using efficient TimeBlock traversal.
        """
        start_str = time_range['start'].isoformat()
        end_str = time_range['end'].isoformat()
        
        activities = []
        
        # Native AQL Query
        query = """
        FOR tb IN TimeBlock
            FILTER tb.start_time >= @start 
            AND tb.end_time <= @end
            AND tb.granularity == 'day'
            AND (tb.user_id == @user_id OR tb.user_id == null)
            
            FOR event IN OUTBOUND tb OCCURRED_DURING
                # Filter for relevant event types
                FILTER event.node_type IN ['Email', 'CalendarEvent', 'Task', 'ActionItem', 'Message']
                
                # Check directly connected relation types if needed, but node_type filter is safer
                RETURN {
                    id: event.id,
                    type: event.node_type,
                    summary: NOT_NULL(event.subject, event.title, event.name, event.text),
                    time: event.timestamp,
                    source: event.source
                }
        """
        
        # Note: The original legacy query matched (event)-[:OCCURRED_DURING]->(tb).
        # In AQL, if edge is (event)->(tb), then from tb to event is INBOUND.
        # Checking schema... usually OCCURRED_DURING is Event->TimeBlock.
        # So tb->event is INBOUND.
        # Let's verify direction. 
        # "MATCH (event)-[:OCCURRED_DURING]->(tb)" means Event is source, TimeBlock is target.
        # So from TimeBlock, we look INBOUND.
        
        query = """
        FOR tb IN TimeBlock
            FILTER tb.start_time >= @start 
               AND tb.end_time <= @end
               AND tb.granularity == 'day'
               AND (tb.user_id == @user_id OR tb.user_id == null)
            
            FOR event IN INBOUND tb OCCURRED_DURING
                RETURN {
                    id: event.id,
                    type: event.node_type,
                    summary: NOT_NULL(event.subject, event.title, event.name, event.text),
                    time: event.timestamp,
                    source: event.source
                }
        """
        # Also need to sort and limit
        query = """
        FOR tb IN TimeBlock
            FILTER tb.start_time >= @start 
               AND tb.end_time <= @end
               AND tb.granularity == 'day'
               AND (tb.user_id == @user_id OR tb.user_id == null)
            
            FOR event IN INBOUND tb OCCURRED_DURING
                SORT event.timestamp ASC
                LIMIT 100
                RETURN {
                    id: event.id,
                    type: event.node_type,
                    summary: NOT_NULL(event.subject, event.title, event.name, event.text),
                    time: event.timestamp,
                    source: event.source
                }
        """
        # Wait, nested LIMIT applies per TB. We want global sort/limit.
        
        query = """
        LET events = (
            FOR tb IN TimeBlock
                FILTER tb.start_time >= @start 
                   AND tb.end_time <= @end
                   AND tb.granularity == 'day'
                   AND (tb.user_id == @user_id OR tb.user_id == null)
                
                FOR event IN INBOUND tb OCCURRED_DURING
                    RETURN event
        )
        
        FOR event IN events
            SORT event.timestamp ASC
            LIMIT 100
            RETURN {
                id: event.id,
                type: event.node_type,
                summary: NOT_NULL(event.subject, event.title, event.name, event.text),
                time: event.timestamp,
                source: event.source
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                'user_id': user_id, 
                'start': start_str, 
                'end': end_str
            })
            
            if results:
                for res in results:
                    # Normalize type for summary generation
                    evt_type = res.get('type', '').lower()
                    if 'email' in evt_type:
                        normalized_type = 'email'
                    elif 'calendarevent' in evt_type:
                        normalized_type = 'meeting'
                    elif 'task' in evt_type or 'actionitem' in evt_type:
                        normalized_type = 'task'
                    else:
                        normalized_type = 'activity'
                        
                    try:
                        # Ensure time is a datetime object
                        time_val = res.get('time')
                        if isinstance(time_val, str):
                            time_val = datetime.fromisoformat(time_val.replace('Z', '+00:00'))
                            
                        activities.append({
                            'id': res.get('id'),
                            'type': normalized_type,
                            'time': time_val,
                            'title': res.get('summary'),
                            'source': res.get('source')
                        })
                    except Exception as e:
                        logger.warning(f"[TemporalReasoner] Failed to parse activity time: {e}")
                        continue
                
        except Exception as e:
            logger.error(f"[TemporalReasoner] Failed to gather activities: {e}")
            
        return activities

    def _generate_temporal_summary(self, activities: List[Dict], time_range: Dict) -> str:
        """
        Generate a natural language summary of the period.
        """
        if not activities:
            return "No significant activity found during this period."
            
        email_count = len([a for a in activities if a['type'] == 'email'])
        meeting_count = len([a for a in activities if a['type'] == 'meeting'])
        
        summary = f"During this period, you sent {email_count} emails and had {meeting_count} meetings."
        
        # Add highlight
        if meeting_count > 0:
            first_meeting = next(a for a in activities if a['type'] == 'meeting')
            summary += f" You started with '{first_meeting.get('title')}'."
            
        return summary

    async def get_relationship_timeline(
        self,
        user_id: int,
        person_id: int, # Graph Node ID or email
        limit_days: int = 90
    ) -> List[TimelineEvent]:
        """
        Build a timeline of all interactions with a specific person.
        """
        events = []
        since_date = (datetime.now() - timedelta(days=limit_days)).isoformat()
        
        # Native AQL with subqueries for Optional Match behavior
        query = """
        LET person = (FOR p IN Person FILTER p.id == @person_id OR p.email == @person_id LIMIT 1 RETURN p)[0]
        
        LET emails = (
            FOR e IN Email
                FILTER e.date >= @since_date
                
                # Check SENT relationship: User -> Email -> Person
                # Or simplistically: Email where sender is User and recipient is Person (or vice versa)
                # Using graph traversal:
                FOR u IN User FILTER u.id == @user_id
                FOR target IN OUTBOUND e TO
                     FILTER target._id == person._id
                FOR sender IN INBOUND e SENT
                     FILTER sender._id == u._id
                
                RETURN {
                    id: e.id, 
                    time: e.date, 
                    type: 'email_sent', 
                    summary: CONCAT('Sent: ', NOT_NULL(e.subject, 'No Subject'))
                }
        )
        
        LET meetings = (
            FOR m IN CalendarEvent
                FILTER m.start_time >= @since_date
                
                # Check ATTENDED relationship: User -> Event <- Person
                FOR u IN User FILTER u.id == @user_id
                FOR p_attendee IN INBOUND m ATTENDED_BY
                    FILTER p_attendee._id == person._id
                FOR u_attendee IN INBOUND m ATTENDED_BY
                    FILTER u_attendee._id == u._id
                    
                RETURN {
                    id: m.id,
                    time: m.start_time,
                    type: 'meeting',
                    summary: CONCAT('Meeting: ', NOT_NULL(m.title, 'Untitled'))
                }
        )
        
        RETURN { interactions: APPEND(emails, meetings) }
        """
        
        # Simplified AQL without complex traversals if possible, assuming direct filtering?
        # But relationships are key.
        # ATTENDED_BY vs ATTENDED: Schema usually has Person -> ATTENDED -> Event (or reverse)
        # Check RelationType: ATTENDED (Person->Event), ATTENDED_BY (Event->Person)?
        # Usually Person -[:ATTENDED]-> CalendarEvent.
        # So INBOUND m ATTENDED is Person.
        
        query = """
        LET person = (FOR p IN Person FILTER p.id == @person_id OR p.email == @person_id LIMIT 1 RETURN p)[0]
        LET user = (FOR u IN User FILTER u.id == @user_id LIMIT 1 RETURN u)[0]
        
        LET emails = (
            FOR e IN Email
                FILTER e.date >= @since_date
                # Verify User SENT it
                FOR s IN INBOUND e SENT
                    FILTER s._id == user._id
                # Verify Person received it (TO)
                FOR r IN OUTBOUND e TO
                    FILTER r._id == person._id
                
                RETURN {
                    id: e.id, 
                    time: e.date, 
                    type: 'email_sent', 
                    summary: CONCAT('Sent: ', NOT_NULL(e.subject, 'No Subject'))
                }
        )
        
        LET meetings = (
            FOR m IN CalendarEvent
                FILTER m.start_time >= @since_date
                # User attended
                FOR ua IN INBOUND m ATTENDED
                    FILTER ua._id == user._id
                # Person attended
                FOR pa IN INBOUND m ATTENDED
                    FILTER pa._id == person._id
                    
                RETURN {
                    id: m.id,
                    time: m.start_time,
                    type: 'meeting',
                    summary: CONCAT('Meeting: ', NOT_NULL(m.title, 'Untitled'))
                }
        )
        
        RETURN { interactions: APPEND(emails, meetings) }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                'user_id': user_id, 
                'person_id': person_id,
                'since_date': since_date
            })
            
            if results and results[0].get('interactions'):
                for item in results[0]['interactions']:
                    if not item or not item.get('time'):
                        continue
                        
                    try:
                        ts = datetime.fromisoformat(str(item['time']).replace('Z', '+00:00'))
                        events.append(TimelineEvent(
                            event_id=item['id'],
                            timestamp=ts,
                            event_type=item['type'],
                            summary=item['summary'],
                            related_people=[], # simplified
                            source='graph'
                        ))
                    except Exception as e:
                        logger.debug(f"[TemporalReasoner] Timeline event timestamp parse failed: {e}")
                        
                # Sort desc
                events.sort(key=lambda x: x.timestamp, reverse=True)
                
        except Exception as e:
            logger.error(f"[TemporalReasoner] Failed to get relationship timeline: {e}")
            
        return events
