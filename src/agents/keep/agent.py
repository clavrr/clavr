"""
Keep Agent

Responsible for handling all note-related queries:
- Creating notes (text or checklist)
- Listing notes
- Searching notes
- Deleting notes

IMPORTANT: Requires Google Workspace Enterprise.
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_KEEP,
    INTENT_KEYWORDS,
    ERROR_NO_TITLE,
    ERROR_AMBIGUOUS_DELETE,
    KEEP_CREATE_KEYWORDS,
    KEEP_DELETE_KEYWORDS,
    KEEP_SEARCH_KEYWORDS,
)
from .schemas import (
    CREATE_NOTE_SCHEMA, SEARCH_NOTE_SCHEMA, DELETE_NOTE_SCHEMA
)

logger = setup_logger(__name__)


class KeepAgent(BaseAgent):
    """
    Specialized agent for Google Keep note operations.
    
    Note: Requires Google Workspace Enterprise account.
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute note-related queries with memory awareness.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context
        if self.memory_orchestrator:
             pass 
             # Optimization: We rely on _extract_params to retrieve memory context
             # to avoid duplicating context in the query string and bloating the prompt.

        query_lower = query.lower()
        
        # Routing logic using centralized keywords
        quick_keywords = INTENT_KEYWORDS.get('notes', {}).get('quick', [])
        
        if any(w in query_lower for w in quick_keywords + KEEP_CREATE_KEYWORDS):
            return await self._handle_create(query, context)
        elif any(w in query_lower for w in KEEP_DELETE_KEYWORDS):
            return await self._handle_delete(query, context)
        elif any(w in query_lower for w in KEEP_SEARCH_KEYWORDS):
            return await self._handle_search(query, context)
        else:
            # Default to list
            return await self._handle_list(query)

    async def _handle_create(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle note creation with LLM extraction"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            CREATE_NOTE_SCHEMA,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        
        tool_input = {
            "action": "create",
            "title": params.get("title", ""),
            "body": params.get("body", ""),
        }
        
        # Handle list items
        items = params.get("items")
        if items:
            if isinstance(items, list):
                tool_input["list_items"] = items
            elif isinstance(items, str):
                tool_input["list_items"] = [i.strip() for i in items.split(',') if i.strip()]
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_KEEP, tool_input, "creating note"
        )

    async def _handle_list(self, query: str) -> str:
        """Handle list notes"""
        tool_input = {"action": "list"}
        return await self._safe_tool_execute(
            TOOL_ALIASES_KEEP, tool_input, "listing notes"
        )

    async def _handle_search(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle search notes"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            SEARCH_NOTE_SCHEMA,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        search_query = params.get("search_query", query)
        
        tool_input = {"action": "search", "query": search_query}
        return await self._safe_tool_execute(
            TOOL_ALIASES_KEEP, tool_input, "searching notes"
        )

    async def _handle_delete(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle delete note"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            DELETE_NOTE_SCHEMA,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        
        if not params.get("note_identifier"):
            return ERROR_AMBIGUOUS_DELETE
        
        tool_input = {
            "action": "delete",
            "note_id": params.get("note_identifier", "")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_KEEP, tool_input, "deleting note"
        )

