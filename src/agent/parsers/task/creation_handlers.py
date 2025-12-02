"""
Task Creation Handlers - Task creation and parsing logic

This module contains handlers for:
- Task creation with classification
- Entity extraction from natural language
- Due date parsing with natural language support  
- Priority and category detection
- LLM-enhanced task parsing
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from ....core.calendar.utils import (
    parse_datetime_with_timezone,
    format_datetime_for_calendar,
    DEFAULT_DURATION_MINUTES
)
from ....ai.prompts import TASK_CREATE_SYSTEM, TASK_CREATE_PROMPT
from ....ai.prompts.utils import format_prompt
from .constants import TaskParserConfig, TaskPriorities, TaskFrequencies

logger = setup_logger(__name__)

# Constants for creation handlers
MIN_DESCRIPTION_LENGTH = TaskParserConfig.MIN_DESCRIPTION_LENGTH
MIN_DESCRIPTION_LENGTH_STRICT = TaskParserConfig.MIN_DESCRIPTION_LENGTH_STRICT
DEFAULT_REMINDER_DAYS = TaskParserConfig.DEFAULT_REMINDER_DAYS
DEFAULT_FREQUENCY = TaskParserConfig.DEFAULT_FREQUENCY


class TaskCreationHandlers:
    """Handlers for task creation and parsing logic"""
    
    def __init__(self, task_parser):
        """Initialize with reference to main TaskParser"""
        self.task_parser = task_parser
        self.logger = logger
    
    def handle_create_action(self, tool: BaseTool, query: str) -> str:
        """Handle create task action"""
        return self._parse_and_create_task(tool, query)
    
    def parse_and_create_task_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any]) -> str:
        """Create task using LLM classification results"""
        logger.info(f"[NOTE] Creating task with classification: {classification}")
        
        # Extract entities from classification
        entities = classification.get("entities", {})
        
        # Build task parameters
        task_params = {}
        
        # Extract description - prefer LLM extraction, fall back to manual
        description = self._extract_task_description_llm(query)
        if not description:
            description = entities.get("task_description") or self._extract_task_description(query, ["create", "add", "make"])
        
        if not description or description.strip() == "":
            return "[ERROR] Could not extract task description from query."
        
        task_params["description"] = description.strip()
        
        # Extract due date
        due_date = self._extract_due_date_with_llm(query)
        if not due_date:
            due_date = entities.get("due_date") or self._extract_due_date(query)
        
        if due_date:
            task_params["due_date"] = due_date
        
        # Extract priority
        priority = self._extract_priority_from_classification(entities)
        if not priority:
            priority = self._extract_priority(query)
        
        if priority and priority != TaskPriorities.MEDIUM:  # Only set if not default
            task_params["priority"] = priority
        
        # Extract category  
        category = self._extract_category_from_classification(entities)
        if not category:
            category = self._extract_category(query)
        
        if category:
            task_params["category"] = category
        
        # Extract other details
        tags = self._extract_tags(query)
        if tags:
            task_params["tags"] = tags
        
        project = self._extract_project(query)
        if project:
            task_params["project"] = project
        
        notes = self._extract_notes(query)
        if notes:
            task_params["notes"] = notes
        
        reminder_days = self._extract_reminder_days(query)
        if reminder_days:
            task_params["reminder_days"] = reminder_days
        
        estimated_hours = self._extract_estimated_hours(query)
        if estimated_hours:
            task_params["estimated_hours"] = estimated_hours
        
        logger.info(f"[NOTE] Creating task with params: {task_params}")
        
        return tool._run(action="create", **task_params)
    
    def parse_and_create_task(self, tool: BaseTool, query: str) -> str:
        """
        Parse task creation with intelligent extraction
        
        Args:
            tool: Task tool
            query: User query
            
        Returns:
            Task creation result
        """
        logger.info(f"[NOTE] Parsing task creation for query: {query}")
        
        # Extract task details
        task_info = self._extract_task_details(query)
        
        logger.info(f"[NOTE] Extracted task: {task_info}")
        
        return tool._run(action="create", **task_info)
    
    def _extract_task_details(self, query: str) -> dict:
        """Extract comprehensive task details from query"""
        task_info = {}
        
        # Core task description
        description = self._extract_task_description(query, ["create", "add", "make", "new", "task"])
        if description:
            task_info["description"] = description
        else:
            # Fallback: use the whole query cleaned up
            cleaned_query = self._extract_actual_query(query)
            task_info["description"] = cleaned_query
        
        # Due date
        due_date = self._extract_due_date(query)
        if due_date:
            task_info["due_date"] = due_date
        
        # Priority
        priority = self._extract_priority(query)
        if priority:
            task_info["priority"] = priority
        
        # Category
        category = self._extract_category(query)
        if category:
            task_info["category"] = category
        
        # Tags
        tags = self._extract_tags(query)
        if tags:
            task_info["tags"] = tags
        
        # Project
        project = self._extract_project(query)
        if project:
            task_info["project"] = project
        
        # Subtasks
        subtasks = self._extract_subtasks(query)
        if subtasks:
            task_info["subtasks"] = subtasks
        
        # Notes
        notes = self._extract_notes(query)
        if notes:
            task_info["notes"] = notes
        
        # Reminder
        reminder_days = self._extract_reminder_days(query)
        if reminder_days is not None:
            task_info["reminder_days"] = reminder_days
        
        # Estimated time
        estimated_hours = self._extract_estimated_hours(query)
        if estimated_hours:
            task_info["estimated_hours"] = estimated_hours
        
        return task_info
    
    def _extract_tags(self, query: str) -> Optional[List[str]]:
        """Extract tags from query"""
        tags = []
        
        # Look for hashtags
        hashtag_matches = re.findall(r'#(\w+)', query)
        tags.extend(hashtag_matches)
        
        # Look for explicit tag mentions
        tag_patterns = [
            r'tag[s]?\s+with\s+([^.]+)',
            r'tag[s]?\s*:\s*([^.]+)',
            r'tagged?\s+([^.]+)'
        ]
        
        for pattern in tag_patterns:
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                tag_text = match.group(1).strip()
                # Split by common delimiters
                new_tags = re.split(r'[,;]\s*', tag_text)
                tags.extend([tag.strip() for tag in new_tags if tag.strip()])
        
        return tags if tags else None
    
    def _extract_project(self, query: str) -> Optional[str]:
        """Extract project from query"""
        patterns = [
            r'project\s+([^.,]+)',
            r'for\s+project\s+([^.,]+)',
            r'in\s+project\s+([^.,]+)',
            r'@(\w+)'  # @project_name format
        ]
        
        for pattern in patterns:
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                return match.group(1).strip()
        
        return None
    
    def _extract_subtasks(self, query: str) -> Optional[List[str]]:
        """Extract subtasks from query"""
        subtasks = []
        
        # Look for explicit subtask indicators
        subtask_patterns = [
            r'subtasks?\s*:\s*([^.]+)',
            r'steps?\s*:\s*([^.]+)',
            r'includes?\s*:\s*([^.]+)'
        ]
        
        for pattern in subtask_patterns:
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                subtask_text = match.group(1).strip()
                # Split by common delimiters
                tasks = re.split(r'[,;]\s*', subtask_text)
                subtasks.extend([task.strip() for task in tasks if task.strip()])
        
        # Look for numbered/bulleted lists
        lines = query.split('\n')
        for line in lines:
            line = line.strip()
            try:
                if re.match(r'^[\d\-•]\s+', line):
                    subtask = re.sub(r'^[\d\-•]\s+', '', line).strip()
                    if subtask:
                        subtasks.append(subtask)
            except re.error:
                pass  # Skip if regex fails
        
        return subtasks if subtasks else None
    
    def _extract_notes(self, query: str) -> Optional[str]:
        """Extract notes/additional details from query"""
        patterns = [
            r'notes?\s*:\s*([^.]+)',
            r'details?\s*:\s*([^.]+)',
            r'info\s*:\s*([^.]+)',
            r'additional\s*:\s*([^.]+)'
        ]
        
        for pattern in patterns:
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                return match.group(1).strip()
        
        return None
    
    def _extract_reminder_days(self, query: str) -> Optional[int]:
        """Extract reminder days from query"""
        patterns = [
            r'remind\s+me\s+(\d+)\s+days?\s+before',
            r'(\d+)\s+days?\s+reminder',
            r'reminder\s+(\d+)\s+days?'
        ]
        
        for pattern in patterns:
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        
        # Default reminders for certain keywords
        try:
            if re.search(r'remind\s+me', query, re.IGNORECASE):
                return DEFAULT_REMINDER_DAYS
        except re.error:
            pass  # Skip if regex fails
        
        return None
    
    def _extract_estimated_hours(self, query: str) -> Optional[float]:
        """Extract estimated time from query"""
        patterns = [
            r'(\d+(?:\.\d+)?)\s+hours?',
            r'takes?\s+(\d+(?:\.\d+)?)\s+hours?',
            r'estimated?\s+(\d+(?:\.\d+)?)\s+hours?',
            r'(\d+(?:\.\d+)?)\s*h(?:r|rs)?',
            r'(\d+)\s+minutes?',  # Convert minutes to hours
        ]
        
        for i, pattern in enumerate(patterns):
            try:
                match = re.search(pattern, query, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                try:
                    value = float(match.group(1))
                    # Convert minutes to hours for the last pattern
                    if i == len(patterns) - 1:  # minutes pattern
                        value = value / 60.0
                    return value
                except ValueError:
                    continue
        
        return None
    
    def _extract_actual_query(self, query: str) -> str:
        """Extract the actual task description, removing action words and markers"""
        # Remove common action phrases
        action_phrases = [
            r'^(create|add|make|new)\s+(a\s+)?(task\s+)?(to\s+)?',
            r'^(please\s+)?(create|add|make|new)\s+(a\s+)?(task\s+)?(to\s+)?',
            r'^(i\s+)?(want\s+to|need\s+to|should)\s+(create|add|make)\s+(a\s+)?(task\s+)?(to\s+)?',
            r'^(task\s*:\s*)',
            r'^(todo\s*:\s*)',
            r'^(reminder\s*:\s*)'
        ]
        
        cleaned = query
        for phrase in action_phrases:
            try:
                cleaned = re.sub(phrase, '', cleaned, flags=re.IGNORECASE).strip()
            except re.error:
                pass  # Skip if regex fails
        
        # If we removed too much, use original
        if len(cleaned) < MIN_DESCRIPTION_LENGTH_STRICT:
            cleaned = query
        
        return cleaned
    
    def _extract_task_description(self, query: str, action_words: list) -> str:
        """
        Extract task description from query using LLM semantic understanding
        
        Args:
            query: Original query
            action_words: List of action words to remove
            
        Returns:
            Cleaned task description
        """
        # PRIORITY 1: Use LLM for semantic extraction
        if self.task_parser.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                import json
                import re
                
                prompt = f"""Extract the task description from this query. Understand semantic meaning, not just literal patterns.

Query: "{query}"

Examples:
- "create a task about calling mom" → "calling mom"
- "add task to buy groceries" → "buy groceries"
- "make a task for gym workout" → "gym workout"
- "new task: review the proposal" → "review the proposal"

Extract the actual task content, removing action words like "create", "add", "make", "task", etc.

Respond with ONLY valid JSON:
{{
    "description": "the task description",
    "confidence": 0.0-1.0
}}"""

                response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    description = result.get('description', '').strip()
                    confidence = result.get('confidence', 0.7)
                    
                    if description and len(description) >= MIN_DESCRIPTION_LENGTH and confidence >= 0.7:
                        logger.info(f"[TASK] LLM extracted description: '{description}' (confidence: {confidence})")
                        return description
            except Exception as e:
                logger.debug(f"[TASK] LLM extraction failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based extraction
        query_lower = query.lower()
        original_query = query
        
        # CRITICAL: Handle "about" patterns first (e.g., "create a task about X")
        # This is common in natural language queries
        about_patterns = [
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?task\s+about\s+(.+)',
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?tasks?\s+about\s+(.+)',
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?task\s+for\s+(.+)',
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?tasks?\s+for\s+(.+)',
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?task\s+to\s+(.+)',
            r'(?:please\s+)?(?:create|add|make|new)\s+(?:a\s+)?tasks?\s+to\s+(.+)',
        ]
        
        for pattern in about_patterns:
            try:
                match = re.search(pattern, query_lower, re.IGNORECASE)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                description = match.group(1).strip()
                if description and len(description) >= MIN_DESCRIPTION_LENGTH:
                    logger.info(f"Extracted description from 'about' pattern: '{description}'")
                    return description
        
        # Remove action words from the beginning
        for action in action_words:
            action_patterns = [
                f'^{action}\\s+',
                f'^{action}\\s+a\\s+',
                f'^{action}\\s+an\\s+',  
                f'^{action}\\s+task\\s+',
                f'^{action}\\s+a\\s+task\\s+',
                f'^{action}\\s+task\\s+to\\s+',
                f'^{action}\\s+a\\s+task\\s+to\\s+',
                f'please\\s+{action}\\s+',
                f'please\\s+{action}\\s+a\\s+',
                f'please\\s+{action}\\s+task\\s+',
                f'please\\s+{action}\\s+a\\s+task\\s+',
            ]
            
            for pattern in action_patterns:
                try:
                    if re.match(pattern, query_lower):
                        # Find the match in the original query to preserve case
                        match = re.match(pattern, query_lower)
                        if match:
                            start_pos = match.end()
                            query = original_query[start_pos:].strip()
                            query_lower = query.lower()
                            break
                except re.error:
                    continue  # Skip if regex fails
        
        # Remove common prefixes
        prefixes_to_remove = [
            r'^(please\s+)?',
            r'^(i\s+want\s+to\s+)?',
            r'^(i\s+need\s+to\s+)?',
            r'^(help\s+me\s+)?',
            r'^(can\s+you\s+)?'
        ]
        
        for prefix in prefixes_to_remove:
            try:
                query = re.sub(prefix, '', query, flags=re.IGNORECASE).strip()
            except re.error:
                pass  # Skip if regex fails
        
        # Remove "about" if it's still at the beginning
        try:
            query = re.sub(r'^about\s+', '', query, flags=re.IGNORECASE).strip()
        except re.error:
            pass  # Skip if regex fails
        
        # Clean up the description
        description = query.strip()
        
        # Ensure we have a valid description
        if not description or len(description) < MIN_DESCRIPTION_LENGTH:
            # If extraction failed, try to get the core action
            description = self._extract_core_action(original_query, original_query)
        
        return description
    
    def _extract_core_action(self, desc: str, original_query: str) -> str:
        """
        Extract the core action/task from a description
        
        Args:
            desc: Task description
            original_query: Original user query
            
        Returns:
            Core action description
        """
        # If description is too short, try to extract from original
        if len(desc.strip()) < MIN_DESCRIPTION_LENGTH_STRICT:
            desc = original_query
        
        # Remove time/date references to focus on the action
        try:
            desc = re.sub(r'\b(today|tomorrow|next week|this week|by|due|on)\b.*', '', desc, flags=re.IGNORECASE)
        except re.error:
            pass  # Skip if regex fails
        
        # Remove priority markers
        try:
            desc = re.sub(r'\b(urgent|high priority|low priority|important)\b', '', desc, flags=re.IGNORECASE)
        except re.error:
            pass  # Skip if regex fails
        
        # Remove category markers
        try:
            desc = re.sub(r'\b(work|personal|home|project)\b', '', desc, flags=re.IGNORECASE)
        except re.error:
            pass  # Skip if regex fails
        
        # Clean up extra spaces
        desc = ' '.join(desc.split())
        
        # If still too short, use the original query
        if len(desc.strip()) < 3:
            desc = original_query
        
        # Common action word mapping - make descriptions more action-oriented
        action_mappings = {
            'call': 'Call',
            'email': 'Send email to',
            'meeting': 'Attend meeting',
            'buy': 'Buy',
            'review': 'Review',
            'update': 'Update',
            'check': 'Check',
            'finish': 'Finish',
            'complete': 'Complete',
            'submit': 'Submit'
        }
        
        desc_lower = desc.lower()
        for trigger, action in action_mappings.items():
            if trigger in desc_lower and not desc_lower.startswith(action.lower()):
                # Try to make it more action-oriented
                desc = f"{action} {desc}"
                break
        
        return desc.strip()
    
    def _extract_priority(self, query: str) -> str:
        """Extract priority level from query"""
        query_lower = query.lower()
        
        # High priority indicators
        high_priority_indicators = [
            "urgent", "asap", "high priority", "important", "critical", 
            "emergency", "!!!", "high", "priority", "crucial", "vital"
        ]
        
        # Low priority indicators  
        low_priority_indicators = [
            "low priority", "when possible", "optional", "maybe", "low", 
            "someday", "eventually", "if time permits"
        ]
        
        # Check for high priority
        for indicator in high_priority_indicators:
            if indicator in query_lower:
                return "high"
        
        # Check for low priority
        for indicator in low_priority_indicators:
            if indicator in query_lower:
                return "low"
        
        # Default is medium
        return "medium"
    
    def _extract_due_date(self, query: str) -> Optional[str]:
        """Extract due date from query using multiple approaches"""
        
        # First try pattern-based extraction
        due_date = self._extract_due_date_patterns(query)
        if due_date:
            return due_date
        
        # Try LLM-based extraction if available
        if self.task_parser.llm_client:
            llm_due_date = self._extract_due_date_with_llm(query)
            if llm_due_date:
                return llm_due_date
        
        return None
    
    def _extract_due_date_patterns(self, query: str) -> Optional[str]:
        """Extract due date using pattern matching"""
        query_lower = query.lower()
        
        # Today/Tomorrow
        if "today" in query_lower:
            return datetime.now().strftime("%Y-%m-%d")
        elif "tomorrow" in query_lower:
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Day names (this week)
        days = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        for day_name, day_num in days.items():
            if day_name in query_lower:
                today = datetime.now()
                days_ahead = (day_num - today.weekday()) % 7
                if days_ahead == 0:  # Today is that day
                    days_ahead = 7  # Next week
                target_date = today + timedelta(days=days_ahead)
                return target_date.strftime("%Y-%m-%d")
        
        # Relative dates
        relative_patterns = [
            (r'in (\d+) days?', lambda x: datetime.now() + timedelta(days=int(x))),
            (r'(\d+) days? from now', lambda x: datetime.now() + timedelta(days=int(x))),
            (r'next week', lambda x: datetime.now() + timedelta(weeks=1)),
            (r'in a week', lambda x: datetime.now() + timedelta(weeks=1)),
            (r'next month', lambda x: datetime.now() + timedelta(days=30)),
            (r'in (\d+) weeks?', lambda x: datetime.now() + timedelta(weeks=int(x)))
        ]
        
        for pattern, date_func in relative_patterns:
            try:
                match = re.search(pattern, query_lower)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                try:
                    if '\\d+' in pattern:
                        target_date = date_func(match.group(1))
                    else:
                        target_date = date_func(None)
                    return target_date.strftime("%Y-%m-%d")
                except (ValueError, IndexError):
                    continue
        
        # Absolute dates
        date_patterns = [
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
            r'(\d{1,2})-(\d{1,2})-(\d{4})',  # MM-DD-YYYY
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
            r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})',  # Month Day
        ]
        
        for pattern in date_patterns:
            try:
                match = re.search(pattern, query_lower)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                try:
                    groups = match.groups()
                    if len(groups) == 3 and groups[0].isdigit():
                        # Numeric date
                        if pattern.startswith(r'(\d{4})'):  # YYYY-MM-DD
                            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                        else:  # MM/DD/YYYY or MM-DD-YYYY
                            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                        
                        target_date = datetime(year, month, day)
                        return target_date.strftime("%Y-%m-%d")
                    elif len(groups) == 2:  # Month Day
                        month_name = groups[0]
                        day = int(groups[1])
                        
                        months = {
                            'january': 1, 'february': 2, 'march': 3, 'april': 4,
                            'may': 5, 'june': 6, 'july': 7, 'august': 8,
                            'september': 9, 'october': 10, 'november': 11, 'december': 12
                        }
                        
                        month_num = months.get(month_name)
                        if month_num:
                            year = datetime.now().year
                            # If the date has passed this year, use next year
                            target_date = datetime(year, month_num, day)
                            if target_date < datetime.now():
                                target_date = datetime(year + 1, month_num, day)
                            return target_date.strftime("%Y-%m-%d")
                except (ValueError, IndexError):
                    continue
        
        return None
    
    def _extract_category(self, query: str) -> Optional[str]:
        """Extract category/context from query"""
        query_lower = query.lower()
        
        # Explicit category patterns
        category_patterns = [
            r'category\s*:\s*([^,\.]+)',
            r'for\s+(work|personal|home|health|finance|shopping|travel)',
            r'(work|personal|home|health|finance|shopping|travel)\s+task',
            r'at\s+(work|home|office|gym|store|bank)',
            r'\[([^\]]+)\]'  # [category] format
        ]
        
        for pattern in category_patterns:
            try:
                match = re.search(pattern, query_lower)
            except re.error as e:
                logger.debug(f"Regex pattern error: {e}")
                continue
            if match:
                category = match.group(1).strip().lower()
                
                # Normalize common categories
                category_mapping = {
                    'office': 'work',
                    'job': 'work',
                    'business': 'work',
                    'house': 'home',
                    'family': 'personal',
                    'gym': 'health',
                    'fitness': 'health',
                    'doctor': 'health',
                    'medical': 'health',
                    'money': 'finance',
                    'budget': 'finance',
                    'bank': 'finance',
                    'buy': 'shopping',
                    'purchase': 'shopping',
                    'store': 'shopping',
                    'trip': 'travel',
                    'vacation': 'travel'
                }
                
                return category_mapping.get(category, category)
        
        # Keyword-based inference
        category_keywords = {
            'work': ['meeting', 'client', 'project', 'deadline', 'presentation', 'report', 'email', 'call'],
            'personal': ['birthday', 'friend', 'family', 'hobby', 'personal'],
            'health': ['doctor', 'appointment', 'medicine', 'exercise', 'workout', 'health'],
            'finance': ['pay', 'bill', 'budget', 'money', 'bank', 'tax', 'expense'],
            'shopping': ['buy', 'purchase', 'groceries', 'store', 'shop', 'order'],
            'home': ['clean', 'repair', 'garden', 'house', 'home', 'maintenance'],
            'travel': ['flight', 'hotel', 'vacation', 'trip', 'travel', 'book']
        }
        
        for category, keywords in category_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                return category
        
        return None
    
    def _extract_task_description_llm(self, query: str) -> Optional[str]:
        """Use LLM to extract task description"""
        if not self.task_parser.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            from ....ai.prompts import TASK_DESCRIPTION_EXTRACTION
            
            prompt = TASK_DESCRIPTION_EXTRACTION.format(query=query)

            response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
            
            if response and hasattr(response, 'content'):
                task_desc = response.content.strip()
            else:
                task_desc = str(response).strip()
            
            # Clean up the response
            task_desc = task_desc.replace('"', '').replace("'", "").strip()
            
            if task_desc and len(task_desc) > MIN_DESCRIPTION_LENGTH and task_desc.lower() != query.lower():
                return task_desc
                
        except Exception as e:
            logger.warning(f"LLM task description extraction failed: {e}")
        
        return None
    
    def _extract_due_date_with_llm(self, query: str) -> Optional[str]:
        """Use LLM to extract due date"""
        if not self.task_parser.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            from ....ai.prompts import TASK_DUE_DATE_EXTRACTION
            
            current_date = datetime.now().strftime("%Y-%m-%d (%A)")
            tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            today_date = datetime.now().strftime('%Y-%m-%d')
            three_days_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
            
            prompt = TASK_DUE_DATE_EXTRACTION.format(
                query=query,
                current_date=current_date,
                tomorrow_date=tomorrow_date,
                today_date=today_date,
                three_days_date=three_days_date
            )

            response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
            
            if response and hasattr(response, 'content'):
                due_date = response.content.strip()
            else:
                due_date = str(response).strip()
            
            # Validate the response
            if due_date and due_date.upper() != "NONE":
                # Check if it's a valid date format
                try:
                    datetime.strptime(due_date, "%Y-%m-%d")
                    return due_date
                except ValueError:
                    pass
                    
        except Exception as e:
            logger.warning(f"LLM due date extraction failed: {e}")
        
        return None
    
    def _extract_priority_from_classification(self, entities: Dict[str, Any]) -> Optional[str]:
        """Extract priority from LLM classification entities"""
        priority = entities.get("priority")
        if priority and isinstance(priority, str):
            priority_lower = priority.lower()
            if priority_lower in ["high", "urgent", "important"]:
                return "high"
            elif priority_lower in ["low", "optional"]:
                return "low"
            else:
                return "medium"
        return None
    
    def _extract_category_from_classification(self, entities: Dict[str, Any]) -> Optional[str]:
        """Extract category from LLM classification entities"""
        category = entities.get("category") or entities.get("context")
        if category and isinstance(category, str):
            return category.lower()
        return None
