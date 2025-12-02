"""
Task Management Handlers - Core task management operations

This module contains handlers for:
- Task completion, deletion, and updates
- Template and recurring task handling
- Bulk operations
- Subtask management
- Reminder and notification handling
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import TaskParserConfig, TaskFrequencies

logger = setup_logger(__name__)

# Constants for management handlers
MIN_DESCRIPTION_LENGTH = TaskParserConfig.MIN_DESCRIPTION_LENGTH
MIN_DESCRIPTION_LENGTH_STRICT = TaskParserConfig.MIN_DESCRIPTION_LENGTH_STRICT
DEFAULT_REMINDER_TIME = "1 day"
DEFAULT_FREQUENCY = TaskParserConfig.DEFAULT_FREQUENCY


class TaskManagementHandlers:
    """Handlers for core task management operations"""
    
    def __init__(self, task_parser):
        """Initialize with reference to main TaskParser"""
        self.task_parser = task_parser
        self.logger = logger
    
    def handle_list_action(self, tool: BaseTool, query: str) -> str:
        """Handle list tasks action"""
        # Check for specific list types
        query_lower = query.lower()
        
        if "overdue" in query_lower:
            return tool._run(action="get_overdue")
        elif "completed" in query_lower or "done" in query_lower:
            return tool._run(action="get_completed")
        elif "high priority" in query_lower or "urgent" in query_lower:
            return tool._run(action="get_by_priority", priority="high")
        elif "today" in query_lower:
            # For "today" queries, show all pending tasks (not just those due today)
            # Users typically mean "what do I need to do today" rather than "what tasks are due today"
            return tool._run(action="list", status="pending")
        else:
            # Default: show all pending tasks
            return tool._run(action="list", status="pending")
    
    def handle_complete_action(self, tool: BaseTool, query: str) -> str:
        """Handle mark task as complete action"""
        # Extract task description or ID
        task_description = self._extract_task_description_for_action(query, ["complete", "done", "finish", "mark"])
        
        if not task_description:
            return "[ERROR] Could not identify task to complete. Please specify task description or ID."
        
        return tool._run(action="complete", task_description=task_description)
    
    def handle_delete_action(self, tool: BaseTool, query: str) -> str:
        """Handle delete task action"""
        # Extract task description or ID
        task_description = self._extract_task_description_for_action(query, ["delete", "remove", "cancel"])
        
        if not task_description:
            return "[ERROR] Could not identify task to delete. Please specify task description or ID."
        
        return tool._run(action="delete", task_description=task_description)
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """Handle search for tasks action"""
        # Extract search terms
        search_terms = self._extract_search_terms(query)
        
        if not search_terms:
            return "[ERROR] Could not identify search terms. Please specify what to search for."
        
        return tool._run(action="search", search_terms=search_terms)
    
    def handle_template_action(self, tool: BaseTool, query: str) -> str:
        """Handle template-related actions"""
        query_lower = query.lower()
        
        if "create" in query_lower or "save" in query_lower:
            # Create template from existing task or new template
            template_name = self._extract_template_name(query)
            task_description = self._extract_task_description_for_action(query, ["template", "create", "save"])
            
            if not template_name:
                return "[ERROR] Could not identify template name. Please specify a name for the template."
            
            if task_description:
                return tool._run(action="create_template", template_name=template_name, task_description=task_description)
            else:
                return tool._run(action="create_template", template_name=template_name)
                
        elif "use" in query_lower or "apply" in query_lower:
            # Use existing template
            template_name = self._extract_template_name(query)
            
            if not template_name:
                return "[ERROR] Could not identify template name. Please specify which template to use."
            
            return tool._run(action="use_template", template_name=template_name)
            
        elif "list" in query_lower:
            # List available templates
            return tool._run(action="list_templates")
            
        elif "delete" in query_lower or "remove" in query_lower:
            # Delete template
            template_name = self._extract_template_name(query)
            
            if not template_name:
                return "[ERROR] Could not identify template name. Please specify which template to delete."
            
            return tool._run(action="delete_template", template_name=template_name)
        
        else:
            # Default to listing templates
            return tool._run(action="list_templates")
    
    def handle_recurring_action(self, tool: BaseTool, query: str) -> str:
        """Handle recurring task actions"""
        query_lower = query.lower()
        
        if "create" in query_lower or "setup" in query_lower or "add" in query_lower:
            # Create recurring task
            task_description = self._extract_task_description_for_action(query, ["recurring", "repeat", "create", "setup"])
            frequency = self._extract_frequency(query)
            
            if not task_description:
                return "[ERROR] Could not identify task description for recurring task."
            
            if not frequency:
                frequency = DEFAULT_FREQUENCY
            
            return tool._run(action="create_recurring", task_description=task_description, frequency=frequency)
            
        elif "stop" in query_lower or "cancel" in query_lower or "disable" in query_lower:
            # Stop recurring task
            task_description = self._extract_task_description_for_action(query, ["recurring", "repeat", "stop", "cancel"])
            
            if not task_description:
                return "[ERROR] Could not identify recurring task to stop."
            
            return tool._run(action="stop_recurring", task_description=task_description)
            
        elif "list" in query_lower:
            # List recurring tasks
            return tool._run(action="list_recurring")
        
        else:
            # Default to listing recurring tasks
            return tool._run(action="list_recurring")
    
    def handle_reminders_action(self, tool: BaseTool, query: str) -> str:
        """Handle reminders and notifications action"""
        query_lower = query.lower()
        
        if "set" in query_lower or "add" in query_lower:
            # Set reminder for task
            task_description = self._extract_task_description_for_action(query, ["reminder", "remind", "set", "add"])
            reminder_time = self._extract_reminder_time(query)
            
            if not task_description:
                return "[ERROR] Could not identify task for reminder."
            
            if not reminder_time:
                reminder_time = DEFAULT_REMINDER_TIME
            
            return tool._run(action="set_reminder", task_description=task_description, reminder_time=reminder_time)
            
        elif "list" in query_lower:
            # List upcoming reminders
            return tool._run(action="list_reminders")
        
        else:
            # Default to listing reminders
            return tool._run(action="list_reminders")
    
    def handle_overdue_action(self, tool: BaseTool, query: str) -> str:
        """Handle get overdue tasks action"""
        return tool._run(action="get_overdue")
    
    def handle_subtasks_action(self, tool: BaseTool, query: str) -> str:
        """Handle get subtasks action"""
        # Extract task ID or description
        task_id = self._extract_task_description_for_action(query, ["subtask", "subtasks", "of"])
        if not task_id:
            return "[ERROR] Could not identify task. Please specify task ID or description."
        
        return tool._run(action="get_subtasks", task_id=task_id)
    
    def handle_bulk_action(self, tool: BaseTool, query: str) -> str:
        """Handle bulk operations"""
        query_lower = query.lower()
        
        if "complete" in query_lower or "finish" in query_lower or "done" in query_lower:
            # Bulk complete
            if "all" in query_lower:
                # Get all pending tasks and complete them
                try:
                    # Get tasks from Google Tasks if available
                    if hasattr(tool, 'google_client') and tool.google_client and tool.google_client.is_available():
                        # Get all pending tasks from Google Tasks
                        tasks = tool.google_client.list_tasks(show_completed=False)
                        if not tasks:
                            return "[TASK] No pending tasks to complete."
                        
                        # Extract task IDs
                        task_ids = [task.get('id') for task in tasks if task.get('id')]
                        
                        if not task_ids:
                            return "[TASK] No task IDs found to complete."
                        
                        # Complete all tasks
                        completed_count = 0
                        for task_id in task_ids:
                            try:
                                tool.google_client.complete_task(task_id=task_id)
                                completed_count += 1
                            except Exception as e:
                                logger.warning(f"Failed to complete task {task_id}: {e}")
                        
                        if completed_count > 0:
                            return f"[TASK] ✅ Successfully marked {completed_count} task{'s' if completed_count != 1 else ''} as done!"
                        else:
                            return "[ERROR] Failed to complete any tasks."
                    else:
                        # Fallback to local storage bulk complete
                        # Get all pending tasks
                        tasks_result = tool._run(action="list", status="pending")
                        # Extract task IDs from the result (simplified)
                        # For now, return a message that we need task IDs
                        return "[INFO] Bulk complete all tasks - please use task IDs or complete tasks individually"
                except Exception as e:
                    logger.error(f"Bulk complete failed: {e}")
                    return f"[ERROR] Failed to complete tasks: {str(e)}"
            return "[ERROR] Please specify which tasks to complete (e.g., 'mark all tasks as done')"
        
        elif "delete" in query_lower or "remove" in query_lower:
            # Bulk delete
            if "all completed" in query_lower:
                return "[INFO] Bulk delete all completed tasks - feature requires task ID extraction"
            return "[ERROR] Please specify which tasks to delete"
        
        return "[ERROR] Unsupported bulk operation"
    
    def _extract_task_description_for_action(self, query: str, action_words: List[str]) -> str:
        """Extract task description for action operations (complete, delete, etc.)"""
        query_lower = query.lower()
        
        # Remove action words and common patterns
        cleaned = query
        for action in action_words:
            patterns = [
                f'^{action}\\s+',
                f'^{action}\\s+task\\s+',
                f'^{action}\\s+the\\s+task\\s+',
                f'^mark\\s+.*?{action}\\s*',
                f'^{action}\\s+.*?task\\s+',
            ]
            for pattern in patterns:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
        
        # Remove common prefixes
        prefixes = [
            r'^(please\\s+)?',
            r'^(can\\s+you\\s+)?', 
            r'^(i\\s+want\\s+to\\s+)?',
            r'^(help\\s+me\\s+)?',
            r'^(task\\s*:\\s*)?',
            r'^(the\\s+)?'
        ]
        
        for prefix in prefixes:
            cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE).strip()
        
        # Look for quoted task descriptions
        quoted_match = re.search(r'["\']([^"\']+)["\']', cleaned)
        if quoted_match:
            return quoted_match.group(1).strip()
        
        # If too short, try to extract the meaningful part
        if len(cleaned) < MIN_DESCRIPTION_LENGTH_STRICT:
            # Look for task descriptions after common patterns
            patterns = [
                r'(?:task|item)\\s+(?:called|named|titled)\\s+(.+)',
                r'(?:the|my)\\s+(.+?)\\s+(?:task|item)',
                r'(.+?)\\s+(?:task|item)',
                r'(?:task|item)\\s+(.+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    result = match.group(1).strip()
                    if len(result) > MIN_DESCRIPTION_LENGTH:
                        return result
        
        return cleaned.strip() if len(cleaned.strip()) > MIN_DESCRIPTION_LENGTH else ""
    
    def _extract_search_terms(self, query: str) -> str:
        """Extract search terms from query"""
        # Remove search action words
        search_words = ["search", "find", "look", "show", "get"]
        cleaned = query
        
        for word in search_words:
            patterns = [
                f'^{word}\\s+',
                f'^{word}\\s+for\\s+',
                f'^{word}\\s+tasks?\\s+',
                f'^{word}\\s+for\\s+tasks?\\s+',
                f'^{word}\\s+tasks?\\s+with\\s+',
                f'^{word}\\s+tasks?\\s+containing\\s+',
                f'^{word}\\s+tasks?\\s+about\\s+',
            ]
            
            for pattern in patterns:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
        
        # Remove common prefixes
        prefixes = [
            r'^(please\\s+)?',
            r'^(can\\s+you\\s+)?',
            r'^(i\\s+want\\s+to\\s+)?',
            r'^(help\\s+me\\s+)?',
            r'^(tasks?\\s+)?',
            r'^(with\\s+)?',
            r'^(containing\\s+)?',
            r'^(about\\s+)?',
        ]
        
        for prefix in prefixes:
            cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE).strip()
        
        # Look for quoted search terms
        quoted_match = re.search(r'["\']([^"\']+)["\']', cleaned)
        if quoted_match:
            return quoted_match.group(1).strip()
        
        return cleaned.strip() if len(cleaned.strip()) > MIN_DESCRIPTION_LENGTH else ""
    
    def _extract_template_name(self, query: str) -> str:
        """Extract template name from query"""
        patterns = [
            r'template\\s+(?:named|called)\\s+["\']([^"\']+)["\']',
            r'template\\s+["\']([^"\']+)["\']',
            r'["\']([^"\']+)["\']\\s+template',
            r'template\\s+(?:named|called)\\s+(.+?)(?:\\s|$)',
            r'(?:save|create)\\s+.*?template\\s+(.+?)(?:\\s|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > MIN_DESCRIPTION_LENGTH:
                    return name
        
        # Fallback: look for any word after "template"
        template_match = re.search(r'template\\s+(\\w+)', query, re.IGNORECASE)
        if template_match:
            return template_match.group(1)
        
        return ""
    
    def _extract_frequency(self, query: str) -> str:
        """Extract frequency for recurring tasks"""
        query_lower = query.lower()
        
        # Frequency mapping
        frequency_patterns = {
            TaskFrequencies.DAILY: ['daily', 'every day', 'each day'],
            TaskFrequencies.WEEKLY: ['weekly', 'every week', 'each week'],
            TaskFrequencies.MONTHLY: ['monthly', 'every month', 'each month'],
            TaskFrequencies.YEARLY: ['yearly', 'annually', 'every year', 'each year'],
            TaskFrequencies.WEEKDAYS: ['weekdays', 'monday to friday', 'mon-fri'],
            TaskFrequencies.WEEKENDS: ['weekends', 'saturday and sunday', 'sat-sun']
        }
        
        # Check for specific frequency patterns
        for frequency, patterns in frequency_patterns.items():
            if any(pattern in query_lower for pattern in patterns):
                return frequency
        
        # Check for custom frequencies like "every 2 days", "every 3 weeks"
        custom_patterns = [
            r'every\\s+(\\d+)\\s+days?',
            r'every\\s+(\\d+)\\s+weeks?',
            r'every\\s+(\\d+)\\s+months?',
        ]
        
        for pattern in custom_patterns:
            match = re.search(pattern, query_lower)
            if match:
                num = match.group(1)
                unit = 'days' if 'day' in pattern else ('weeks' if 'week' in pattern else 'months')
                return f"every_{num}_{unit}"
        
        # Default to configured frequency
        return DEFAULT_FREQUENCY
    
    def _extract_reminder_time(self, query: str) -> str:
        """Extract reminder time from query"""
        patterns = [
            r'(\\d+)\\s+(?:days?|day)\\s+before',
            r'(\\d+)\\s+(?:hours?|hour)\\s+before', 
            r'(\\d+)\\s+(?:minutes?|min)\\s+before',
            r'remind\\s+me\\s+(\\d+)\\s+(?:days?|day)',
            r'remind\\s+me\\s+(\\d+)\\s+(?:hours?|hour)',
            r'remind\\s+me\\s+(\\d+)\\s+(?:minutes?|min)',
            r'(\\d+)\\s*(?:days?|day)',
            r'(\\d+)\\s*(?:hours?|hour|h)',
            r'(\\d+)\\s*(?:minutes?|min|m)',
        ]
        
        query_lower = query.lower()
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                num = match.group(1)
                if 'day' in pattern:
                    return f"{num} days"
                elif 'hour' in pattern or 'h' in pattern:
                    return f"{num} hours"
                elif 'min' in pattern or 'm' in pattern:
                    return f"{num} minutes"
        
        # Check for relative times
        if 'tomorrow' in query_lower:
            return "1 day"
        elif 'tonight' in query_lower or 'evening' in query_lower:
            return "4 hours"
        elif 'morning' in query_lower:
            return "12 hours"
        
        return DEFAULT_REMINDER_TIME
    
    def _format_fallback_response(self, formatted_result: str, action_type: str, task_description: Optional[str] = None) -> str:
        """Format fallback response when LLM is unavailable (delegated to parent)"""
        return self.task_parser._format_fallback_response(formatted_result, action_type, task_description)
