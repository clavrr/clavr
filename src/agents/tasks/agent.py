"""
Task Agent

Responsible for handling all task-related queries:
- Creating tasks
- Listing tasks
- Completing tasks
- Analyzing tasks
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_TASKS,
    INTENT_KEYWORDS,
    ERROR_NO_TITLE,
    ERROR_AMBIGUOUS_COMPLETE
)
from .schemas import (
    CREATE_TASK_SCHEMA, COMPLETE_TASK_SCHEMA
)

logger = setup_logger(__name__)

class TaskAgent(BaseAgent):
    """
    Specialized agent for Task operations (Google Tasks).
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute task-related queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        query_lower = query.lower()
        
        # Priority order: list → complete → create (to avoid misclassifying "summarize tasks" as create)
        if any(w in query_lower for w in INTENT_KEYWORDS['tasks']['list']):
             return await self._handle_list(query, context)
        elif any(w in query_lower for w in INTENT_KEYWORDS['tasks']['complete']):
            return await self._handle_complete(query, context)
        elif any(w in query_lower for w in INTENT_KEYWORDS['tasks']['create']):
            return await self._handle_create(query, context)
        else:
            # Default to list/search
            return await self._handle_list(query, context)

    async def _handle_create(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task creation with LLM extraction"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            CREATE_TASK_SCHEMA, 
            user_id=user_id,
            task_type="planning"
        )
        if not params.get("title"):
            # Fallback if extraction fails
            return ERROR_NO_TITLE

        tool_input = {
            "action": "create",
            "title": params["title"],
            "due_date": params.get("due_date"),
            "priority": params.get("priority")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_TASKS, tool_input, "creating task"
        )

    async def _handle_list(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task listing"""
        tool_input = {"action": "list", "query": query}
        return await self._safe_tool_execute(
            TOOL_ALIASES_TASKS, tool_input, "listing tasks"
        )

    async def _handle_complete(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task completion"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            COMPLETE_TASK_SCHEMA, 
            user_id=user_id,
            task_type="planning"
        )
        if not params.get("task_title"):
            return ERROR_AMBIGUOUS_COMPLETE
            
        tool_input = {
            "action": "complete",
            "query": params["task_title"]
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_TASKS, tool_input, "completing task"
        )
