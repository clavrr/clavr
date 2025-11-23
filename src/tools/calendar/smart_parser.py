"""
Smart Calendar Query Parser

Parses natural language calendar queries into structured actions with context.
Handles complex queries like:
- "Reschedule my 3pm meeting to tomorrow at 2pm"
- "What meetings do I have next week and what are the action items?"
- "Schedule a recurring meeting every Tuesday and Thursday at 10am PST"
- "Move my standup to the afternoon at 2pm"
- "Book a team meeting and invite peter and carol"
- "Find free time for a 1-hour meeting tomorrow"
- "Cancel my 3pm meeting with peter"
"""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import re

from ...utils.logger import setup_logger
from ...core.calendar.utils import DEFAULT_DURATION_MINUTES, DEFAULT_DAYS_AHEAD
from ..constants import ToolConfig

logger = setup_logger(__name__)

# Constants for smart parser
MINUTES_PER_HOUR = 60
DAYS_TODAY = 0
DAYS_TOMORROW = 1
DAYS_YESTERDAY = -1
DAYS_NEXT_WEEK = 7
DAYS_THIS_WEEK = 0
DAYS_NEXT_MONTH = 30
DAYS_THIS_MONTH = 0
DEFAULT_CONFIDENCE_HIGH = 0.9
DEFAULT_CONFIDENCE_MEDIUM = 0.8
DEFAULT_CONFIDENCE_LOW = 0.0


class SmartCalendarParser:
    """Parse natural language calendar queries into structured actions"""
    
    # Action patterns with priority (most specific first)
    ACTION_PATTERNS = [
        # Reschedule patterns
        (r'(?:reschedule|move|change)\s+(?:my\s+)?(.+?)\s+(?:to|at)\s+(.+)', 'reschedule'),
        (r'(?:reschedule|move|change)\s+(.+)', 'reschedule'),
        
        # Cancel/Delete patterns
        (r'(?:cancel|delete|remove)\s+(?:my\s+)?(.+)', 'cancel'),
        
        # Create patterns
        (r'(?:schedule|book|create|add)\s+(?:a\s+)?(?:recurring\s+)?(.+)', 'create'),
        
        # Find free time patterns
        (r'(?:find|show|get)\s+(?:me\s+)?(?:some\s+)?free\s+time\s+(?:for\s+)?(.+)', 'find_free_time'),
        (r'when\s+(?:am\s+i|are\s+we)\s+(?:free|available)\s+(?:for\s+)?(.+)', 'find_free_time'),
        
        # List patterns with action items
        (r'(?:what|show|list)\s+(?:meetings?|events?|classes?)\s+(?:do\s+i\s+have\s+)?(.+?)\s+(?:and\s+)?(?:what\s+are\s+)?(?:the\s+)?(?:action\s+items?)?', 'list_with_actions'),
        
        # List patterns
        (r'(?:what|show|list)\s+(?:meetings?|events?|classes?)\s+(?:do\s+i\s+have\s+)?(.+)', 'list'),
        (r'(?:my\s+)?(?:meetings?|events?|classes?)\s+(?:for\s+)?(.+)', 'list'),
        
        # Update patterns
        (r'(?:update|modify|edit)\s+(.+)', 'update'),
    ]
    
    # Time reference patterns
    TIME_REFERENCES = {
        'today': DAYS_TODAY,
        'tomorrow': DAYS_TOMORROW,
        'yesterday': DAYS_YESTERDAY,
        'next week': DAYS_NEXT_WEEK,
        'this week': DAYS_THIS_WEEK,
        'next month': DAYS_NEXT_MONTH,
        'this month': DAYS_THIS_MONTH,
    }
    
    # Recurring patterns
    RECURRING_PATTERNS = [
        (r'every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)', 'weekly'),
        (r'every\s+(\w+)\s+and\s+(\w+)', 'multiple_days'),
        (r'(?:daily|every\s+day)', 'daily'),
        (r'(?:weekly|every\s+week)', 'weekly'),
        (r'(?:monthly|every\s+month)', 'monthly'),
        (r'(?:first|second|third|fourth|last)\s+(\w+)\s+of\s+(?:each|every)\s+month', 'monthly_ordinal'),
    ]
    
    def __init__(self):
        """Initialize the smart parser"""
        pass
    
    def parse_query(self, query: str) -> Dict[str, Any]:
        """
        Parse a natural language calendar query
        
        Args:
            query: Natural language query
            
        Returns:
            Dictionary with parsed action, entities, and context
        """
        query_lower = query.lower().strip()
        
        result = {
            'action': None,
            'original_query': query,
            'entities': {},
            'context': {},
            'confidence': DEFAULT_CONFIDENCE_LOW
        }
        
        # Detect action type
        action_info = self._detect_action(query_lower)
        if action_info:
            result['action'] = action_info['action']
            result['context']['pattern'] = action_info.get('pattern')
            result['confidence'] = action_info.get('confidence', DEFAULT_CONFIDENCE_MEDIUM)
        
        # Extract entities based on action
        if result['action'] == 'reschedule':
            result['entities'] = self._extract_reschedule_entities(query_lower)
        elif result['action'] == 'cancel':
            result['entities'] = self._extract_cancel_entities(query_lower)
        elif result['action'] == 'create':
            result['entities'] = self._extract_create_entities(query_lower, query)
        elif result['action'] == 'find_free_time':
            result['entities'] = self._extract_free_time_entities(query_lower)
        elif result['action'] in ['list', 'list_with_actions']:
            result['entities'] = self._extract_list_entities(query_lower)
            result['context']['include_action_items'] = result['action'] == 'list_with_actions'
        
        # Extract common entities
        result['entities'].update(self._extract_common_entities(query_lower, query))
        
        logger.info(f"[SmartParser] Query: '{query}' -> Action: {result['action']}, Entities: {result['entities']}")
        
        return result
    
    def _detect_action(self, query: str) -> Optional[Dict[str, Any]]:
        """Detect the primary action from the query"""
        for pattern, action in self.ACTION_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return {
                    'action': action,
                    'pattern': pattern,
                    'match': match.groups(),
                    'confidence': DEFAULT_CONFIDENCE_HIGH
                }
        return None
    
    def _extract_reschedule_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities for reschedule action"""
        entities = {}
        
        # Pattern: "reschedule my 3pm meeting to tomorrow at 2pm"
        # Pattern: "move my standup to the afternoon at 2pm"
        
        # Extract event identifier (time or name)
        event_pattern = r'(?:my\s+)?(?:(\d+(?::\d+)?\s*(?:am|pm)?)\s+)?(\w+(?:\s+\w+)*?)\s+(?:meeting|event|class)?'
        match = re.search(event_pattern, query)
        if match:
            if match.group(1):
                entities['event_time'] = match.group(1).strip()
            if match.group(2):
                entities['event_name'] = match.group(2).strip()
        
        # Extract new time
        to_pattern = r'(?:to|at)\s+(.+?)(?:\s+and\s+|\s*$)'
        match = re.search(to_pattern, query)
        if match:
            entities['new_time'] = match.group(1).strip()
        
        return entities
    
    def _extract_cancel_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities for cancel action"""
        entities = {}
        
        # Pattern: "cancel my 3pm meeting with peter"
        
        # Extract event identifier
        event_pattern = r'(?:my\s+)?(?:(\d+(?::\d+)?\s*(?:am|pm)?)\s+)?(\w+(?:\s+\w+)*?)\s+(?:meeting|event|class)?'
        match = re.search(event_pattern, query)
        if match:
            if match.group(1):
                entities['event_time'] = match.group(1).strip()
            if match.group(2):
                entities['event_name'] = match.group(2).strip()
        
        # Extract attendees
        with_pattern = r'with\s+([\w\s,]+?)(?:\s+and\s+|\s*$)'
        match = re.search(with_pattern, query)
        if match:
            attendees_str = match.group(1).strip()
            entities['attendees'] = [name.strip() for name in re.split(r',|\s+and\s+', attendees_str)]
        
        return entities
    
    def _extract_create_entities(self, query: str, original_query: str) -> Dict[str, Any]:
        """Extract entities for create action"""
        entities = {}
        
        # Check for recurring pattern
        is_recurring = 'recurring' in query or 'every' in query
        entities['is_recurring'] = is_recurring
        
        if is_recurring:
            # Extract recurrence pattern
            for pattern, recur_type in self.RECURRING_PATTERNS:
                match = re.search(pattern, query)
                if match:
                    entities['recurrence_type'] = recur_type
                    entities['recurrence_pattern'] = match.group(0)
                    if match.groups():
                        entities['recurrence_days'] = list(match.groups())
                    break
        
        # Extract meeting title/type
        title_pattern = r'(?:schedule|book|create)\s+(?:a\s+)?(?:recurring\s+)?(.+?)(?:\s+(?:every|at|for|with|on)|\s*$)'
        match = re.search(title_pattern, query)
        if match:
            entities['title'] = match.group(1).strip()
        
        # Extract time if specified
        time_pattern = r'(?:at|@)\s+(\d+(?::\d+)?\s*(?:am|pm)?(?:\s+[A-Z]{3})?)'
        match = re.search(time_pattern, original_query, re.IGNORECASE)
        if match:
            entities['time'] = match.group(1).strip()
        
        # Extract date references
        date_pattern = r'(?:on|for)\s+(tomorrow|today|next\s+\w+|this\s+\w+|\w+day)'
        match = re.search(date_pattern, query)
        if match:
            entities['date'] = match.group(1).strip()
        
        return entities
    
    def _extract_free_time_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities for find free time action"""
        entities = {}
        
        # Extract duration
        duration_pattern = r'(?:for\s+)?(?:a\s+)?(\d+)\s*(?:-\s*)?(?:hour|hr|minute|min)s?'
        match = re.search(duration_pattern, query)
        if match:
            duration = int(match.group(1))
            if 'hour' in query or 'hr' in query:
                entities['duration_minutes'] = duration * MINUTES_PER_HOUR
            else:
                entities['duration_minutes'] = duration
        
        # Extract date reference
        date_pattern = r'(?:for|on)\s+(tomorrow|today|next\s+\w+|this\s+\w+)'
        match = re.search(date_pattern, query)
        if match:
            entities['date'] = match.group(1).strip()
        
        return entities
    
    def _extract_list_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities for list action"""
        entities = {}
        
        # Extract time range
        time_range_pattern = r'(?:for|in|this|next)\s+(week|month|today|tomorrow)'
        match = re.search(time_range_pattern, query)
        if match:
            entities['time_range'] = match.group(1).strip()
        
        # Detect event type
        if 'class' in query:
            entities['event_type'] = 'class'
        elif 'meeting' in query:
            entities['event_type'] = 'meeting'
        
        return entities
    
    def _extract_common_entities(self, query: str, original_query: str) -> Dict[str, Any]:
        """Extract common entities across all actions"""
        entities = {}
        
        # Extract attendees (people to invite)
        invite_pattern = r'(?:invite|with|and)\s+([\w\s,]+?)(?:\s+(?:and|,)\s+|\s*$)'
        matches = re.findall(invite_pattern, query)
        if matches:
            attendees = []
            for match in matches:
                # Split by 'and' or ','
                names = re.split(r',|\s+and\s+', match.strip())
                attendees.extend([name.strip() for name in names if name.strip()])
            if attendees:
                entities['attendees'] = list(set(attendees))  # Remove duplicates
        
        # Extract time references
        for ref, days in self.TIME_REFERENCES.items():
            if ref in query:
                entities['time_reference'] = ref
                entities['days_offset'] = days
                break
        
        # Extract specific times
        time_pattern = r'(\d+(?::\d+)?\s*(?:am|pm))'
        matches = re.findall(time_pattern, query, re.IGNORECASE)
        if matches:
            entities['times'] = matches
        
        # Extract duration from title or context
        duration_pattern = r'(\d+)\s*(?:-\s*)?(?:hour|hr|minute|min)s?'
        match = re.search(duration_pattern, query)
        if match and 'duration_minutes' not in entities:
            duration = int(match.group(1))
            if 'hour' in query or 'hr' in query:
                entities['duration_minutes'] = duration * MINUTES_PER_HOUR
            else:
                entities['duration_minutes'] = duration
        
        return entities
    
    def build_calendar_action(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a CalendarTool action from parsed query
        
        Args:
            parsed: Parsed query result
            
        Returns:
            Dictionary with action and parameters for CalendarTool
        """
        action = parsed.get('action')
        entities = parsed.get('entities', {})
        
        if action == 'reschedule':
            return self._build_reschedule_action(entities)
        elif action == 'cancel':
            return self._build_cancel_action(entities)
        elif action == 'create':
            return self._build_create_action(entities)
        elif action == 'find_free_time':
            return self._build_free_time_action(entities)
        elif action in ['list', 'list_with_actions']:
            return self._build_list_action(entities, parsed.get('context', {}))
        
        return {'action': 'unknown', 'params': {}}
    
    def _build_reschedule_action(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Build reschedule action parameters"""
        # This is a multi-step action:
        # 1. Find the event by time/name
        # 2. Check for conflicts at new time
        # 3. Move the event
        
        return {
            'action': 'reschedule',
            'multi_step': True,
            'steps': [
                {
                    'action': 'search',
                    'params': {
                        'query': entities.get('event_name', ''),
                        'start_time': entities.get('event_time'),
                    }
                },
                {
                    'action': 'check_conflicts',
                    'params': {
                        'start_time': entities.get('new_time'),
                        'duration_minutes': DEFAULT_DURATION_MINUTES
                    }
                },
                {
                    'action': 'move_event',
                    'params': {
                        'new_start_time': entities.get('new_time')
                    }
                }
            ]
        }
    
    def _build_cancel_action(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Build cancel action parameters"""
        return {
            'action': 'cancel',
            'multi_step': True,
            'steps': [
                {
                    'action': 'search',
                    'params': {
                        'query': entities.get('event_name', ''),
                        'start_time': entities.get('event_time'),
                    }
                },
                {
                    'action': 'delete',
                    'params': {}
                }
            ]
        }
    
    def _build_create_action(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Build create action parameters"""
        params = {
            'title': entities.get('title', 'New Event'),
            'start_time': entities.get('time') or entities.get('date', 'tomorrow at 9am'),
            'duration_minutes': entities.get('duration_minutes', DEFAULT_DURATION_MINUTES),
        }
        
        if entities.get('attendees'):
            params['attendees'] = entities['attendees']
        
        if entities.get('is_recurring') and entities.get('recurrence_pattern'):
            params['recurrence'] = entities['recurrence_pattern']
        
        return {
            'action': 'create',
            'params': params
        }
    
    def _build_free_time_action(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Build find free time action parameters"""
        return {
            'action': 'find_free_time',
            'params': {
                'duration_minutes': entities.get('duration_minutes', DEFAULT_DURATION_MINUTES),
                'start_date': entities.get('date'),
            }
        }
    
    def _build_list_action(self, entities: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Build list action parameters"""
        params = {}
        
        # Map time range to days_ahead
        time_range = entities.get('time_range', 'week')
        if time_range == 'today':
            params['days_ahead'] = DAYS_TOMORROW
            params['days_back'] = DAYS_TODAY
        elif time_range == 'tomorrow':
            params['days_ahead'] = DAYS_TOMORROW + 1  # Tomorrow + 1 day = 2 days ahead
            params['days_back'] = DAYS_TODAY
        elif time_range == 'week':
            params['days_ahead'] = DAYS_NEXT_WEEK
        elif time_range == 'month':
            params['days_ahead'] = DAYS_NEXT_MONTH
        else:
            # Default to DEFAULT_DAYS_AHEAD from calendar utils
            params['days_ahead'] = DEFAULT_DAYS_AHEAD
        
        return {
            'action': 'list',
            'params': params,
            'include_action_items': context.get('include_action_items', False)
        }
