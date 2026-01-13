"""
Asana Agent

Responsible for handling all Asana-related queries:
- Creating tasks
- Listing tasks
- Completing tasks
- Searching tasks
- Project management
"""
from typing import Dict, Any, Optional

from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import INTENT_KEYWORDS, TOOL_ALIASES_ASANA

logger = setup_logger(__name__)


class AsanaAgent(BaseAgent):
    """
    Specialized agent for Asana task operations.
    
    Handles task management queries and routes them to the appropriate
    AsanaTool actions.
    """
    
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute Asana-related queries.
        
        Args:
            query: User query
            context: Optional context
            
        Returns:
            Response string
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # Extract user_id for personalization
        user_id = context.get('user_id') if context else None
        
        # Use centralized keywords
        asana_keywords = INTENT_KEYWORDS.get('asana', {})
        
        # Route using BaseAgent helper
        routes = {
            "create": asana_keywords.get('create', []),
            "complete": asana_keywords.get('complete', []),
            "search": asana_keywords.get('search', []),
            "delete": asana_keywords.get('delete', []),
            "projects": asana_keywords.get('projects', []),
        }
        
        action = self._route_query(query, routes)
        
        if action == "create":
            return await self._handle_create(query, context)
        elif action == "complete":
            return await self._handle_complete(query, context)
        elif action == "search":
            return await self._handle_search(query)
        elif action == "delete":
            return await self._handle_delete(query)
        elif action == "projects":
            return await self._handle_projects(query)
        else:
            # Default to list
            return await self._handle_list(query)
    
    async def _handle_create(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task creation with LLM extraction."""
        user_id = context.get('user_id') if context else None
        schema = {
            "title": "The main task description or title",
            "due_date": "Due date if specified (iso format or relative like 'tomorrow'), else null",
            "notes": "Additional notes or details, else null",
            "project": "Project name if specified, else null"
        }
        
        params = await self._extract_params(
            query, schema, 
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        if not params.get("title"):
            return "I need a task title to create an Asana task."
        
        tool_input = {
            "action": "create",
            "title": params["title"],
            "due_date": params.get("due_date"),
            "notes": params.get("notes"),
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_ASANA, tool_input, "creating Asana task"
        )
    
    async def _handle_list(self, query: str) -> str:
        """Handle task listing."""
        query_lower = query.lower()
        
        status = "pending"
        if "completed" in query_lower or "done" in query_lower:
            status = "completed"
        elif "all" in query_lower:
            status = "all"
        elif "overdue" in query_lower:
            return await self._safe_tool_execute(
                TOOL_ALIASES_ASANA, {"action": "overdue"}, "checking overdue tasks"
            )
        
        tool_input = {"action": "list", "status": status}
        return await self._safe_tool_execute(
            TOOL_ALIASES_ASANA, tool_input, "listing Asana tasks"
        )
    
    async def _handle_complete(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task completion."""
        user_id = context.get('user_id') if context else None
        schema = {
            "task_title": "The title or keywords of the task to complete"
        }
        
        params = await self._extract_params(
            query, schema,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        if not params.get("task_title"):
            return "I'm not sure which task you want to complete."
        
        tool_input = {
            "action": "complete",
            "query": params["task_title"]
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_ASANA, tool_input, "completing Asana task"
        )
    
    async def _handle_search(self, query: str) -> str:
        """Handle task search."""
        # Extract search query - remove common search keywords
        search_query = query.lower()
        for word in ['search', 'find', 'look for', 'asana', 'tasks', 'task']:
            search_query = search_query.replace(word, '')
        search_query = search_query.strip()
        
        if not search_query:
            return "What would you like me to search for in Asana?"
        
        tool_input = {"action": "search", "query": search_query}
        return await self._safe_tool_execute(
            TOOL_ALIASES_ASANA, tool_input, "searching Asana tasks"
        )
    
    async def _handle_delete(self, query: str) -> str:
        """Handle task deletion."""
        return "Task deletion requires a specific task ID. Please search for the task first."
    
    async def _handle_projects(self, query: str) -> str:
        """Handle project listing."""
        tool_input = {"action": "projects"}
        return await self._safe_tool_execute(
            TOOL_ALIASES_ASANA, tool_input, "listing Asana projects"
        )

