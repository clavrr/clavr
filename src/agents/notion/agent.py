"""
Notion Agent

Responsible for handling all Notion-related queries:
- searching pages/databases
- reading content
- writing content
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_NOTION,
    INTENT_KEYWORDS,
    ERROR_NO_PAGE_TITLE,
    ERROR_AMBIGUOUS_UPDATE,
    NOTION_UPDATE_KEYWORDS,
)

logger = setup_logger(__name__)

class NotionAgent(BaseAgent):
    """
    Specialized agent for Notion operations.
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute Notion-related queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        query_lower = query.lower()
        
        # Routing logic using centralized keywords
        create_keywords = INTENT_KEYWORDS.get('notion', {}).get('create', [])
        
        if any(w in query_lower for w in create_keywords):
            return await self._handle_create(query, context)
        elif any(w in query_lower for w in NOTION_UPDATE_KEYWORDS):
            return await self._handle_update(query, context)
        else:
            # Default to search/query
            return await self._handle_search(query)

    async def _handle_create(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle page creation with LLM extraction"""
        user_id = context.get('user_id') if context else None
        schema = {
            "title": "Title of the new page",
            "content": "Content or body of the new page",
            "parent_page_id": "ID of parent page if specified, else null"
        }
        
        params = await self._extract_params(
            query, schema,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        if not params.get("title"):
            return ERROR_NO_PAGE_TITLE
             
        tool_input = {
            "action": "create_page",
            "title": params["title"],
            "content": params.get("content", ""),
            "parent_id": params.get("parent_page_id")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_NOTION, tool_input, "creating page"
        )

    async def _handle_search(self, query: str) -> str:
        """Handle search"""
        tool_input = {"action": "search", "query": query}
        return await self._safe_tool_execute(
            TOOL_ALIASES_NOTION, tool_input, "searching Notion"
        )

    async def _handle_update(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle page updates with LLM extraction"""
        user_id = context.get('user_id') if context else None
        schema = {
            "page_keyword": "Title or keyword to find the page to update",
            "new_content": "New content to append or replace, else null",
            "new_title": "New title if renaming, else null"
        }
        
        params = await self._extract_params(
            query, schema,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        if not params.get("page_keyword"):
            return ERROR_AMBIGUOUS_UPDATE.format(item_type="page")
             
        tool_input = {
            "action": "update_page",
            "query": params["page_keyword"],
            "content": params.get("new_content"),
            "title": params.get("new_title")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_NOTION, tool_input, "updating page"
        )

