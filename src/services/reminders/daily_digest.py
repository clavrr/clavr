"""
Daily Digest Generator Service.

Generates the "Your day ahead" briefing by aggregating:
- Urgent actionable items (bills, deadlines)
- Today's calendar schedule
- Upcoming important items
- Intelligent recommendations

Mimics the structure of a high-value executive assistant daily brief.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import ActionableItem
from src.services.indexing.graph.manager import KnowledgeGraphManager

logger = setup_logger(__name__)

class DailyDigestGenerator:
    """Generates the daily 'Your day ahead' digest."""
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        
    async def generate_digest(self, user_id: int) -> Dict[str, Any]:
        """
        Build the full daily digest.
        
        Returns a dict structured for the UI/Email template:
        {
            "date": "Wednesday, Dec 16",
            "greeting": "Morning, Maniko. Here's your game plan!",
            "top_of_mind": [...],
            "schedule": [...],
            "upcoming": [...]
        }
        """
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # parallel fetch
        action_coro = self._get_actionable_items(user_id)
        schedule_coro = self._get_today_schedule(user_id, today_start, today_end)
        
        actions, schedule = await asyncio.gather(action_coro, schedule_coro)
        
        # Process actions into groups
        top_of_mind = []
        upcoming = []
        
        for item in actions:
            if item.get('urgency') == 'high' or self._is_due_today(item.get('due_date')):
                top_of_mind.append(self._format_action_item(item))
            else:
                upcoming.append(self._format_action_item(item))
                
        # Sort by urgency/date
        top_of_mind.sort(key=lambda x: x['due_date'] or '')
        upcoming.sort(key=lambda x: x['due_date'] or '')
        
        digest = {
            "date": now.strftime("%A, %b %d"),
            "greeting": f"Morning. Here's your game plan for the day!",
            "top_of_mind": top_of_mind[:5],  # Top 5 most urgent
            "schedule": schedule[:5],        # Next 5 meetings
            "upcoming": upcoming[:5],        # Review later
            "generated_at": now.isoformat()
        }
        
        return digest

    async def _get_actionable_items(self, user_id: int) -> List[Dict]:
        """Fetch pending items from graph/database."""
        query = """
        FOR a IN ActionableItem
            FILTER a.user_id == @user_id AND a.status == 'pending'
            SORT a.due_date ASC
            LIMIT 20
            RETURN a
        """
        # In a real app, we'd query SQL or Graph. 
        # For now, leveraging GraphManager if ActionableItems are nodes, 
        # OR usually we'd use a DB session here. 
        # Assuming ActionableItems are ALSO indexed into Graph or we have a DAO.
        
        # Placeholder depending on architecture choices.
        # Since I added SQL model, I should query SQL. 
        # But for this service, I'll mock the DB query via graph or assume graph sync.
        # Let's assume we use the graph for fast retrieval or just SQL via session.
        # Given existing patterns, let's allow passing a db_session or use simple query.
        
        # Simplified: Retrieval logic to be connected to DB
        return []

    async def _get_today_schedule(self, user_id: int, start: datetime, end: datetime) -> List[Dict]:
        """Fetch today's calendar events."""
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id 
               AND e.start_time >= @start
               AND e.start_time < @end
            SORT e.start_time ASC
            RETURN {
                title: e.title,
                time: e.start_time,
                location: e.location
            }
        """
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "start": start.isoformat(),
                "end": end.isoformat()
            })
            return [
                {
                    "title": r["title"],
                    "time": datetime.fromisoformat(r["time"].replace('Z', '+00:00')).strftime("%I:%M %p"),
                    "location": r.get("location")
                }
                for r in (results or [])
            ]
        except Exception as e:
            logger.error(f"Failed to fetch today's schedule for user {user_id}: {e}", exc_info=True)
            return []

    def _is_due_today(self, due_date_str: Optional[str]) -> bool:
        if not due_date_str:
            return False
        try:
            due = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
            now = datetime.utcnow()
            return due.date() == now.date() or due < now
        except ValueError:
            return False

    def _format_action_item(self, item: Dict) -> Dict:
        """Format item for the digest view."""
        # Calculate time estimate based on complexity (simulated)
        time_est = "5 min"
        if item.get('item_type') == 'bill':
            time_est = "5 min"
        elif item.get('item_type') == 'deadline':
            time_est = "30 min"
            
        return {
            "title": item.get('title'),
            "time_estimate": time_est,
            "due_label": self._get_due_label(item.get('due_date')),
            "action_label": item.get('suggested_action', 'View'),
            "type": item.get('item_type'),
            "due_date": item.get('due_date')
        }

    def _get_due_label(self, due_date_str: Optional[str]) -> str:
        if not due_date_str:
            return ""
        try:
            due = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
            now = datetime.utcnow()
            
            if due.date() == now.date():
                return "(due today)"
            elif due.date() == (now + timedelta(days=1)).date():
                return "(due tomorrow)"
            else:
                return f"(due {due.strftime('%b %d')})"
        except ValueError:
            return ""
