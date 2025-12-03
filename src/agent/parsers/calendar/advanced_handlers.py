"""
Calendar Advanced Handlers

Handles advanced calendar features:
- Follow-up actions: Tracks and extracts follow-up items from meetings
- Action item extraction: Identifies and categorizes action items in event descriptions
- Meeting preparation: Generates preparation checklists for upcoming meetings
- Related meeting linking: Groups meetings by common topics and projects
- Meetings with action items: Lists meetings and their associated action items

This module integrates with:
- CalendarParser: Parent parser for configuration and utility methods
- ConfigManager: For loading action patterns and response templates
- Event parsing system: For structured event extraction

Note: All patterns and configurations are centralized in intent_patterns.py and config
to ensure consistency across the application.
"""
import re
from typing import Dict, Any, Optional, List
from langchain.tools import BaseTool

from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Import centralized patterns and config
try:
    from ...intent import (
        CALENDAR_ADVANCED_ACTION_PATTERNS,
        CALENDAR_FOLLOWUP_PATTERNS,
        CALENDAR_ACTION_ITEM_PATTERNS,
    )
except ImportError:
    # Fallback patterns if imports fail
    CALENDAR_ADVANCED_ACTION_PATTERNS = {
        'followup': ['follow up', 'followup', 'next steps', 'action needed'],
        'action_items': ['action item', 'todo', 'ai:', 'task:', 'checkbox'],
        'related': ['related', 'similar', 'same project', 'same team'],
        'preparation': ['prepare', 'prep', 'preparation', 'get ready'],
    }
    CALENDAR_FOLLOWUP_PATTERNS = [
        r'follow[-\s]up:?\s*(.+?)(?:\n|$)',
        r'next steps:?\s*(.+?)(?:\n|$)',
        r'follow up with\s+(.+?)(?:\n|$)',
        r'action needed:?\s*(.+?)(?:\n|$)',
    ]
    CALENDAR_ACTION_ITEM_PATTERNS = [
        r'(?:TODO|Action Item|AI|ACTION):?\s*(.+?)(?:\n|$)',
        r'\[\s*(?:x|✓)?\s*\]\s*(.+?)(?:\n|$)',  # Checkbox format
        r'(?:^|\n)[\s]*[-•]\s+(?:\[.*?\])?\s*(.+?)(?:\n|$)',  # Bullet points
    ]

# Response formatting templates
RESPONSE_TEMPLATES = {
    'followup_found': 'I found {count} follow-up item(s) from your meetings:',
    'followup_not_found': 'I didn\'t find any explicit follow-up items in your recent meetings.',
    'action_items_found': 'I found {count} action item(s):',
    'action_items_not_found': 'I didn\'t find any action items in the meeting descriptions.',
    'meetings_found': 'Here are your meetings with action items:',
    'meetings_not_found': 'I found meetings but none have action items recorded.',
    'related_found': 'I found {count} group(s) of related meetings:',
    'related_not_found': 'I couldn\'t find any obvious groups of related meetings.',
    'prep_checklist': 'Preparation for: {title}',
    'error': 'I encountered an error: {error}',
}


class CalendarAdvancedHandlers:
    """
    Handles advanced calendar operations.
    
    Advanced features include:
    - Follow-up management: Extract and track follow-up items from meetings
    - Action item extraction: Identify action items in meeting descriptions
    - Meetings with action items: List meetings and their action items
    - Related meeting linking: Group meetings by common topics
    - Meeting preparation: Generate preparation information for upcoming meetings
    
    All patterns and configurations are loaded from the calendar parser to ensure
    consistency and avoid hardcoding values.
    """
    
    def __init__(self, calendar_parser):
        """
        Initialize advanced handlers.
        
        Args:
            calendar_parser: Parent CalendarParser instance for accessing:
                - Configuration and settings
                - Tool access
                - Date/time parsing utilities
                - Response formatting methods
        """
        self.calendar_parser = calendar_parser
        self.logger = logger
        
        # Load max results from config or use defaults
        self.max_results_default = getattr(
            getattr(calendar_parser, 'config', None),
            'max_calendar_results',
            20
        )
        self.max_results_extended = getattr(
            getattr(calendar_parser, 'config', None),
            'max_calendar_results_extended',
            50
        )
        self.max_related_groups = 5
        
        # Load response templates from config or use defaults
        self.templates = getattr(
            getattr(calendar_parser, 'config', None),
            'response_templates',
            RESPONSE_TEMPLATES
        )
    
    def handle_followup_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle follow-up actions from meetings.
        
        Extracts and displays follow-up items tracked in meeting descriptions.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting follow-up information
            
        Returns:
            Formatted list of follow-up items from recent meetings
        """
        try:
            self.logger.info(f"[ADVANCED] Handling follow-up action for query: '{query}'")
            
            # Get recent events using configured max results
            result = tool._run(action="list", time_min=None, max_results=self.max_results_default)
            
            if not result or "error" in result.lower():
                return "I couldn't retrieve your meetings to check for follow-ups. Please try again."
            
            # Parse events
            events = self._parse_events_from_result(result)
            
            if not events:
                return "You don't have any recent meetings with follow-up items."
            
            # Extract follow-up items from event descriptions
            followups = self._extract_items_by_pattern(events, CALENDAR_FOLLOWUP_PATTERNS, 'followup')
            
            if not followups:
                return self.templates['followup_not_found']
            
            # Format response
            msg = self.templates['followup_found'].format(count=len(followups)) + "\n\n"
            for i, item in enumerate(followups, 1):
                msg += f"{i}. **{item['meeting']}**\n"
                msg += f"   Follow-up: {item['action']}\n"
                if item.get('due_date'):
                    msg += f"   Due: {item['due_date']}\n"
                msg += "\n"
            
            return msg
            
        except Exception as e:
            self.logger.error(f"Follow-up action failed: {e}", exc_info=True)
            return self.templates['error'].format(error=str(e))
    
    def handle_extract_action_items_action(self, tool: BaseTool, query: str) -> str:
        """
        Extract action items from meeting descriptions.
        
        Identifies action items marked with common conventions (TODO, [], bullet points, etc.)
        in meeting event descriptions.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting action item extraction
            
        Returns:
            Extracted and formatted action items from meetings
        """
        try:
            self.logger.info(f"[ADVANCED] Extracting action items for query: '{query}'")
            
            # Extract event title from query if specified
            event_title = self._extract_event_title_from_query(query)
            
            if event_title:
                # Get specific event
                result = tool._run(action="search", query=event_title, max_results=5)
            else:
                # Get recent events
                result = tool._run(action="list", time_min=None, max_results=self.max_results_default)
            
            if not result or "error" in result.lower():
                return "I couldn't retrieve meeting details to extract action items. Please try again."
            
            # Parse events
            events = self._parse_events_from_result(result)
            
            if not events:
                return "I couldn't find any meetings to extract action items from."
            
            # Extract action items using centralized patterns
            action_items = self._extract_items_by_pattern(events, CALENDAR_ACTION_ITEM_PATTERNS, 'action_item')
            
            if not action_items:
                return self.templates['action_items_not_found']
            
            # Format response
            msg = self.templates['action_items_found'].format(count=len(action_items)) + "\n\n"
            for i, item in enumerate(action_items, 1):
                msg += f"{i}. {item['action']}\n"
                msg += f"   From: **{item['meeting']}**\n"
                if item.get('owner'):
                    msg += f"   Owner: {item['owner']}\n"
                msg += "\n"
            
            return msg
            
        except Exception as e:
            self.logger.error(f"Extract action items failed: {e}", exc_info=True)
            return self.templates['error'].format(error=str(e))
    
    def handle_meetings_with_action_items(self, tool: BaseTool, query: str) -> str:
        """
        List meetings along with their action items.
        
        Retrieves a list of meetings and their associated action items in a single view.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting meetings and action items
            
        Returns:
            Meetings with their associated action items
        """
        try:
            self.logger.info(f"[ADVANCED] Getting meetings with action items for query: '{query}'")
            
            # Get meetings based on query time period
            result = tool._run(action="list", time_min=None, max_results=self.max_results_default)
            
            if not result or "error" in result.lower():
                return "I couldn't retrieve your meetings right now. Please try again."
            
            # Parse events
            events = self._parse_events_from_result(result)
            
            if not events:
                return "You don't have any meetings to show."
            
            # Build response with meetings and their action items
            msg = self.templates['meetings_found'] + "\n\n"
            meetings_with_items = 0
            
            for event in events:
                # Extract action items for this event
                action_items = self._extract_action_items_for_event(event)
                
                if action_items:
                    meetings_with_items += 1
                    msg += f"**{event.get('summary', 'Untitled Meeting')}**\n"
                    if event.get('time'):
                        msg += f"Time: {event['time']}\n"
                    msg += f"Action Items:\n"
                    for item in action_items:
                        msg += f"  • {item}\n"
                    msg += "\n"
            
            if meetings_with_items == 0:
                return self.templates['meetings_not_found']
            
            return msg
            
        except Exception as e:
            self.logger.error(f"Meetings with action items failed: {e}", exc_info=True)
            return self.templates['error'].format(error=str(e))
    
    def handle_link_related_meetings_action(self, tool: BaseTool, query: str) -> str:
        """
        Find and link related meetings by topic or project.
        
        Groups meetings by common keywords in titles to identify meetings
        related to the same project or topic.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting related meetings
            
        Returns:
            Groups of related meetings organized by topic
        """
        try:
            self.logger.info(f"[ADVANCED] Finding related meetings for query: '{query}'")
            
            # Get all meetings using extended result limit
            result = tool._run(action="list", time_min=None, max_results=self.max_results_extended)
            
            if not result or "error" in result.lower():
                return "I couldn't retrieve your meetings to find related ones. Please try again."
            
            # Parse events
            events = self._parse_events_from_result(result)
            
            if not events:
                return "You don't have any meetings to link."
            
            # Find related meetings by grouping similar titles/topics
            related_groups = self._group_related_meetings(events)
            
            if not related_groups:
                return self.templates['related_not_found']
            
            # Format response
            msg = self.templates['related_found'].format(count=len(related_groups)) + "\n\n"
            for i, group in enumerate(related_groups, 1):
                msg += f"{i}. **{group['topic']}** ({group['count']} meetings)\n"
                # Show first 3 meetings
                for meeting in group['meetings'][:3]:
                    msg += f"   • {meeting.get('summary', 'Untitled')}\n"
                if group['count'] > 3:
                    msg += f"   ... and {group['count'] - 3} more\n"
                msg += "\n"
            
            return msg
            
        except Exception as e:
            self.logger.error(f"Link related meetings failed: {e}", exc_info=True)
            return self.templates['error'].format(error=str(e))
    
    def handle_prepare_meeting_action(self, tool: BaseTool, query: str) -> str:
        """
        Help prepare for an upcoming meeting.
        
        Generates a comprehensive preparation checklist for a meeting including
        meeting details, previous action items, and preparation steps.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting meeting preparation
            
        Returns:
            Meeting preparation information and suggestions
        """
        try:
            self.logger.info(f"[ADVANCED] Preparing for meeting: '{query}'")
            
            # Extract meeting title from query
            meeting_title = self._extract_event_title_from_query(query)
            
            if meeting_title:
                # Search for specific meeting
                result = tool._run(action="search", query=meeting_title, max_results=5)
            else:
                # Get next upcoming meeting
                result = tool._run(action="list", time_min=None, max_results=5)
            
            if not result or "error" in result.lower():
                return "I couldn't find the meeting to help you prepare. Please specify which meeting."
            
            # Parse events
            events = self._parse_events_from_result(result)
            
            if not events:
                return "I couldn't find the meeting you want to prepare for."
            
            # Get the first/most relevant meeting
            meeting = events[0]
            
            # Build preparation checklist
            prep_info = self._build_meeting_preparation(meeting)
            
            msg = f"**{self.templates['prep_checklist'].format(title=meeting.get('summary', 'Your Meeting'))}**\n\n"
            
            if meeting.get('time'):
                msg += f"📅 Time: {meeting['time']}\n"
            if meeting.get('location'):
                msg += f"📍 Location: {meeting['location']}\n"
            msg += "\n"
            
            if prep_info['has_description']:
                msg += "**Meeting Details:**\n"
                msg += f"{prep_info['description']}\n\n"
            
            if prep_info['action_items']:
                msg += "**Previous Action Items:**\n"
                for item in prep_info['action_items']:
                    msg += f"  • {item}\n"
                msg += "\n"
            
            msg += "**Preparation Checklist:**\n"
            msg += "  ☐ Review meeting agenda\n"
            if prep_info['has_attendees']:
                msg += "  ☐ Confirm attendee availability\n"
            if meeting.get('location'):
                msg += "  ☐ Test meeting link/room setup\n"
            msg += "  ☐ Prepare any necessary materials\n"
            msg += "  ☐ Review previous meeting notes\n"
            
            return msg
            
        except Exception as e:
            self.logger.error(f"Prepare meeting failed: {e}", exc_info=True)
            return self.templates['error'].format(error=str(e))
    
    # ==================== Helper Methods ====================
    
    def _parse_events_from_result(self, result: str) -> List[Dict[str, Any]]:
        """
        Parse structured events from calendar tool result.
        
        Converts raw calendar result string into structured event dictionaries
        containing summary, time, location, description, and attendees.
        
        Args:
            result: Raw calendar tool result string
            
        Returns:
            List of parsed event dictionaries
        """
        events = []
        
        try:
            lines = result.split('\n')
            current_event = {}
            
            for line in lines:
                if re.match(r'^\d+\.', line):
                    if current_event:
                        events.append(current_event)
                    current_event = {'summary': line.split('.', 1)[1].strip() if '.' in line else line}
                elif any(key in line for key in ['Time:', 'When:'] ):
                    current_event['time'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif 'Location:' in line:
                    current_event['location'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif 'Description:' in line:
                    current_event['description'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif 'Attendees:' in line:
                    current_event['attendees'] = line.split(':', 1)[1].strip() if ':' in line else ''
            
            if current_event:
                events.append(current_event)
                
        except Exception as e:
            self.logger.warning(f"Failed to parse events: {e}")
        
        return events
    
    def _extract_items_by_pattern(
        self,
        events: List[Dict[str, Any]],
        patterns: List[str],
        item_type: str
    ) -> List[Dict[str, Any]]:
        """
        Extract items (followups, action items, etc.) from events using regex patterns.
        
        Centralized extraction method that applies patterns to event descriptions
        and extracts structured items with metadata.
        
        Args:
            events: List of parsed event dictionaries
            patterns: List of regex patterns to match
            item_type: Type of item being extracted ('followup', 'action_item', etc.)
            
        Returns:
            List of extracted items with metadata
        """
        items = []
        
        for event in events:
            description = event.get('description', '')
            if not description:
                continue
                
            for pattern in patterns:
                try:
                    matches = re.finditer(pattern, description, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        action_text = match.group(1).strip()
                        if not action_text:
                            continue
                        
                        # Extract owner if present (e.g., "@John")
                        owner_match = re.search(r'@(\w+)', action_text)
                        owner = owner_match.group(1) if owner_match else None
                        
                        items.append({
                            'meeting': event.get('summary', 'Untitled'),
                            'action': action_text,
                            'owner': owner,
                            'due_date': None,  # Could be extracted if present
                            'type': item_type
                        })
                except Exception as e:
                    self.logger.debug(f"Pattern matching failed for {item_type}: {e}")
                    continue
        
        return items
    
    def _extract_action_items_for_event(self, event: Dict[str, Any]) -> List[str]:
        """
        Extract action items for a specific event.
        
        Convenience method that uses the centralized extraction with action item patterns.
        
        Args:
            event: Event dictionary
            
        Returns:
            List of extracted action item strings
        """
        items = []
        description = event.get('description', '')
        
        if description:
            for pattern in CALENDAR_ACTION_ITEM_PATTERNS:
                try:
                    matches = re.finditer(pattern, description, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        item_text = match.group(1).strip()
                        if item_text:
                            items.append(item_text)
                except Exception as e:
                    self.logger.debug(f"Action item extraction failed: {e}")
                    continue
        
        return items
    
    def _extract_event_title_from_query(self, query: str) -> Optional[str]:
        """
        Extract event title from user query.
        
        Uses heuristic patterns to identify meeting titles mentioned in queries like
        "prepare for X meeting" or "action items from X".
        
        Args:
            query: User query string
            
        Returns:
            Extracted meeting title or None
        """
        query_lower = query.lower()
        
        # Patterns like "for X meeting" or "prepare for X"
        patterns = [
            r'for\s+(?:the\s+)?([^,\.]+?)\s+meeting',
            r'(?:prepare|prep|get ready)\s+(?:for\s+)?(?:the\s+)?(.+?)(?:\s+meeting)?$',
            r'(?:action items?|followup|items?)\s+(?:from|in)\s+(?:the\s+)?(.+?)(?:\s+meeting)?$',
            r'about\s+(?:the\s+)?(.+?)(?:\s+meeting)?$',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                title = match.group(1).strip()
                # Filter out common words
                if title and len(title) > 2 and title not in ['meeting', 'event', 'appointment']:
                    return title
        
        return None
    
    def _group_related_meetings(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Group meetings by common keywords in titles.
        
        Uses TF-IDF inspired approach: extracts significant words from meeting titles
        and groups meetings that share those keywords. Filters out common words.
        
        Args:
            events: List of event dictionaries
            
        Returns:
            List of grouped meetings with topic information
        """
        # Common words to exclude from grouping
        common_words = {
            'meeting', 'sync', 'call', 'check', 'stand', 'up', 'standup',
            'discussion', 'review', 'update', 'session', 'talk', 'chat',
            'connect', 'touch', 'base', '1on1', 'one', 'on', 'catch', 'quick'
        }
        
        groups = {}
        
        for event in events:
            title = event.get('summary', '').lower()
            # Extract significant words (ignore common words and short words)
            words = [
                w.strip(',.') for w in title.split()
                if len(w.strip(',.')) > 4 and w.lower() not in common_words
            ]
            
            for word in words:
                if word not in groups:
                    groups[word] = []
                groups[word].append(event)
        
        # Filter groups with more than 1 meeting
        related = []
        for topic, meetings in groups.items():
            if len(meetings) > 1:
                related.append({
                    'topic': topic.title(),
                    'count': len(meetings),
                    'meetings': meetings
                })
        
        # Sort by count descending
        related.sort(key=lambda x: x['count'], reverse=True)
        
        return related[:self.max_related_groups]
    
    def _build_meeting_preparation(self, meeting: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build comprehensive meeting preparation information.
        
        Gathers all relevant information for preparing for a meeting including
        description, attendees, and previous action items.
        
        Args:
            meeting: Meeting event dictionary
            
        Returns:
            Dictionary with preparation information
        """
        prep = {
            'has_description': bool(meeting.get('description')),
            'description': meeting.get('description', ''),
            'has_attendees': bool(meeting.get('attendees')),
            'action_items': []
        }
        
        # Extract any action items from description
        if prep['has_description']:
            prep['action_items'] = self._extract_action_items_for_event(meeting)
        
        return prep
