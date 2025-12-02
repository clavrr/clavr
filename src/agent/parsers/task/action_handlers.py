"""
Task Action Handlers - Handle specific task actions like create, complete, delete, etc.
"""
from typing import Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class TaskActionHandlers:
    """Handles specific task actions and operations"""
    
    def __init__(self, task_parser):
        self.task_parser = task_parser
        self.llm_client = task_parser.llm_client
    
    def handle_analyze_action(self, tool: BaseTool, query: str) -> str:
        """Handle task analysis action"""
        return tool._run(action="analyze", query=query)
    
    def handle_create_action(self, tool: BaseTool, query: str) -> str:
        """Handle task creation action"""
        return self.task_parser.creation_handlers.parse_and_create_task(tool, query)
    
    def handle_list_action(self, tool: BaseTool, query: str) -> str:
        """Handle task listing action"""
        # Determine if this is a filtered list or general list
        query_lower = query.lower()
        
        if "overdue" in query_lower or "late" in query_lower:
            return tool._run(action="list", filter="overdue")
        elif "completed" in query_lower or "done" in query_lower:
            return tool._run(action="list", filter="completed")
        elif "high priority" in query_lower or "urgent" in query_lower:
            return tool._run(action="list", filter="priority:high")
        else:
            return tool._run(action="list")
    
    def handle_complete_action(self, tool: BaseTool, query: str) -> str:
        """Handle task completion action"""
        # Extract task ID or description from query
        task_id = self.extract_task_identifier(query)
        if task_id:
            return tool._run(action="complete", task_id=task_id)
        else:
            return tool._run(action="complete", query=query)
    
    def handle_delete_action(self, tool: BaseTool, query: str) -> str:
        """Handle task deletion action"""
        # Extract task ID or description from query
        task_id = self.extract_task_identifier(query)
        if task_id:
            return tool._run(action="delete", task_id=task_id)
        else:
            return tool._run(action="delete", query=query)
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """Handle task search action"""
        # Extract search criteria from query
        search_query = self.extract_search_criteria(query)
        return tool._run(action="search", query=search_query)
    
    def handle_analytics_action(self, tool: BaseTool, query: str) -> str:
        """Handle analytics action - delegates to analytics_handlers"""
        return self.task_parser.analytics_handlers.handle_analytics_action(tool, query)
    
    def handle_template_action(self, tool: BaseTool, query: str) -> str:
        """Handle template-related actions"""
        query_lower = query.lower()
        
        if "create template" in query_lower:
            # Extract template name and structure from query
            template_name = self.extract_template_name(query)
            return tool._run(action="create_template", name=template_name, query=query)
        elif "use template" in query_lower:
            # Find and apply template
            template_name = self.extract_template_name(query)
            return tool._run(action="use_template", name=template_name, query=query)
        else:
            # List available templates
            return tool._run(action="list_templates")
    
    def handle_recurring_action(self, tool: BaseTool, query: str) -> str:
        """Handle recurring task actions"""
        # Extract recurrence pattern from query
        recurrence = self.extract_recurrence_pattern(query)
        return tool._run(action="create_recurring", recurrence=recurrence, query=query)
    
    def handle_reminders_action(self, tool: BaseTool, query: str) -> str:
        """Handle reminder actions"""
        # Extract reminder time from query
        reminder_time = self.extract_reminder_time(query)
        return tool._run(action="set_reminder", time=reminder_time, query=query)
    
    def handle_overdue_action(self, tool: BaseTool, query: str) -> str:
        """Handle overdue task queries"""
        return tool._run(action="list", filter="overdue")
    
    def extract_task_identifier(self, query: str) -> Optional[str]:
        """Extract task ID or identifier from query"""
        import re
        
        # Look for task ID patterns
        patterns = [
            r'task[:\s]+(\d+)',
            r'id[:\s]+(\d+)',
            r'#(\d+)',
            r'task\s+(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def extract_search_criteria(self, query: str) -> str:
        """Extract search criteria from search query"""
        # Remove common search prefixes
        search_prefixes = [
            "find task", "search task", "search for task",
            "look for task", "find", "search"
        ]
        
        search_query = query.lower()
        for prefix in search_prefixes:
            if search_query.startswith(prefix):
                search_query = search_query[len(prefix):].strip()
                break
        
        return search_query or query
    
    def extract_template_name(self, query: str) -> Optional[str]:
        """Extract template name from query"""
        import re
        
        patterns = [
            r'template[:\s]+"([^"]+)"',
            r'template[:\s]+([^\s]+)',
            r'"([^"]+)"\s*template'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def extract_recurrence_pattern(self, query: str) -> Optional[str]:
        """Extract recurrence pattern from query"""
        query_lower = query.lower()
        
        if "daily" in query_lower:
            return "daily"
        elif "weekly" in query_lower:
            return "weekly"
        elif "monthly" in query_lower:
            return "monthly"
        elif "yearly" in query_lower:
            return "yearly"
        else:
            return "once"
    
    def extract_reminder_time(self, query: str) -> Optional[str]:
        """Extract reminder time from query"""
        import re
        
        # Look for time patterns
        time_patterns = [
            r'(\d+)\s*(minutes?|mins?)\s*(before|ahead)',
            r'(\d+)\s*(hours?|hrs?)\s*(before|ahead)',
            r'(\d+)\s*(days?)\s*(before|ahead)',
            r'at\s+(\d{1,2}):(\d{2})',
            r'(\d{1,2})\s*(am|pm)'
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(0)
        
        return None
