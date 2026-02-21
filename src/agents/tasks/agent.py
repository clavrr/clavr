"""
Task Agent

Responsible for handling all task-related queries:
- Creating tasks
- Listing tasks
- Completing tasks
- Analyzing tasks
"""
import re
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_TASKS,
    TOOL_ALIASES_ASANA,
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

    def _select_task_tool_aliases(self, query: str, context: Optional[Dict[str, Any]] = None):
        """Choose Google Tasks or Asana tool aliases based on intent and active integrations."""
        query_lower = (query or "").lower()
        active_providers = set((context or {}).get("active_providers", []))

        explicitly_asana = "asana" in query_lower
        explicitly_google_tasks = "google tasks" in query_lower or "google task" in query_lower

        if explicitly_asana:
            return TOOL_ALIASES_ASANA

        if explicitly_google_tasks:
            return TOOL_ALIASES_TASKS

        # If only Asana is connected for task workflows, default to Asana.
        if "asana" in active_providers and "google_tasks" not in active_providers:
            return TOOL_ALIASES_ASANA

        return TOOL_ALIASES_TASKS

    @staticmethod
    def _is_asana_routing(tool_aliases) -> bool:
        """Return True when request is routed to Asana-backed task operations."""
        return "asana" in [a.lower() for a in tool_aliases]

    @staticmethod
    def _extract_project_name(query: str) -> Optional[str]:
        """Lightweight fallback parser for project names in natural language."""
        if not query:
            return None

        patterns = [
            r"project\s+called\s+['\"]?([^,.\n]+?)['\"]?(?:\s+in\s+asana|\s+today|$)",
            r"project\s+named\s+['\"]?([^,.\n]+?)['\"]?(?:\s+in\s+asana|\s+today|$)",
            r"create\s+(?:a\s+)?project\s+['\"]?([^,.\n]+?)['\"]?(?:\s+in\s+asana|\s+today|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" .,!\"'")
                if value:
                    return value
        return None

    @staticmethod
    def _contains_phrase(query: str, phrase: str) -> bool:
        """Boundary-aware phrase check to avoid substring false positives (e.g. create vs created)."""
        if not query or not phrase:
            return False
        pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\b"
        return re.search(pattern, query, flags=re.IGNORECASE) is not None
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute task-related queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        query_lower = query.lower()
        tool_aliases = self._select_task_tool_aliases(query, context)
        project_create_intent = any(
            self._contains_phrase(query, phrase)
            for phrase in ["create project", "create a project", "new project", "project called", "project named"]
        )

        if (
            self._is_asana_routing(tool_aliases)
            and project_create_intent
            and "task" not in query_lower
        ):
            return await self._handle_create_project(query, context)

        explicit_create_intent = any(
            self._contains_phrase(query, verb)
            for verb in ["create", "add", "make", "new task", "new todo", "remind me"]
        )
        
        # Priority order: create → complete → list
        # Create must be checked FIRST because queries like "add a task about X" 
        # can also contain list keywords (e.g., "task"/"tasks"), causing misrouting.
        if explicit_create_intent or any(w in query_lower for w in INTENT_KEYWORDS['tasks']['create']):
            return await self._handle_create(query, context)
        elif any(w in query_lower for w in INTENT_KEYWORDS['tasks']['complete']):
            return await self._handle_complete(query, context)
        elif any(w in query_lower for w in INTENT_KEYWORDS['tasks']['list']):
             return await self._handle_list(query, context)
        else:
            # If intent is ambiguous but includes task nouns, prefer create over list.
            if " task" in f" {query_lower}" or "todo" in query_lower:
                return await self._handle_create(query, context)
            return await self._handle_list(query, context)

    async def _handle_create_project(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle project creation for Asana-backed task workflows."""
        user_id = context.get('user_id') if context else None
        tool_aliases = self._select_task_tool_aliases(query, context)

        if not self._is_asana_routing(tool_aliases):
            return "Project creation is currently supported for Asana task workflows."

        schema = {
            "project_name": "Project name to create in Asana",
            "notes": "Optional project description/notes"
        }
        params = await self._extract_params(
            query,
            schema,
            user_id=user_id,
            task_type="planning"
        )

        project_name = (params.get("project_name") or self._extract_project_name(query) or "").strip()
        if not project_name:
            return "I couldn't identify the project name. Please rephrase with 'project called <name>'."

        tool_input = {
            "action": "create_project",
            "project_name": project_name,
            "notes": params.get("notes")
        }
        return await self._safe_tool_execute(tool_aliases, tool_input, "creating project")

    async def _handle_create(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task creation with LLM extraction"""
        user_id = context.get('user_id') if context else None
        tool_aliases = self._select_task_tool_aliases(query, context)
        
        params = await self._extract_params(
            query, 
            CREATE_TASK_SCHEMA, 
            user_id=user_id,
            task_type="planning"
        )
        if not params.get("title"):
            # Fallback if extraction fails
            return ERROR_NO_TITLE

        project_name = params.get("project_name")
        if not project_name:
            match = re.search(r"in\s+(?:the\s+)?([^,.\n]+?)\s+project", query, flags=re.IGNORECASE)
            if match:
                project_name = match.group(1).strip(" .,!\"'")

        tool_input = {
            "action": "create",
            "title": params["title"],
            "due_date": params.get("due_date"),
            "priority": params.get("priority"),
            "project_name": project_name,
            "notes": params.get("notes")
        }
        
        return await self._safe_tool_execute(
            tool_aliases, tool_input, "creating task"
        )

    async def _handle_list(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task listing"""
        tool_aliases = self._select_task_tool_aliases(query, context)
        query_lower = (query or "").lower()

        if self._is_asana_routing(tool_aliases) and "project" in query_lower and "task" not in query_lower:
            tool_input = {"action": "projects", "query": query}
            return await self._safe_tool_execute(
                tool_aliases, tool_input, "listing projects"
            )

        tool_input = {"action": "list", "query": query}
        return await self._safe_tool_execute(
            tool_aliases, tool_input, "listing tasks"
        )

    async def _handle_complete(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle task completion"""
        user_id = context.get('user_id') if context else None
        tool_aliases = self._select_task_tool_aliases(query, context)
        
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
            tool_aliases, tool_input, "completing task"
        )
