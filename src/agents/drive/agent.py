"""
Google Drive Agent

Handles active interactions with Google Drive:
- List recent files
- Search files
- Read file content
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_DRIVE,
    INTENT_KEYWORDS
)
from .schemas import DRIVE_INTENT_SCHEMA
from .constants import DAYS_PATTERN_LAST
import re

logger = setup_logger(__name__)


class DriveAgent(BaseAgent):
    """
    Specialized agent for Google Drive operations.
    
    Uses DriveTool for all file operations, with credentials
    provided via AppState (matching EmailAgent pattern).
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute drive-related queries with memory awareness.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context
        if self.memory_orchestrator:
             pass 
             # Optimization: We rely on _extract_params to retrieve memory context (via task_type='retrieval')
             # to avoid duplicating context in the query string and bloating the prompt.

        # 2. Unified Intent & Param Extraction
        try:
            params = await self._extract_params(
                query,
                DRIVE_INTENT_SCHEMA,
                user_id=context.get('user_id') if context else None,
                task_type="simple_extraction"
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Extraction failed: {e}. Falling back to list.")
            params = {"action": "list"}

        action = params.get("action", "list")
        
        # Map to Tool Input
        tool_input = {"action": action, "query": query} # Default query is raw query
        
        if action == "search":
            # Use the LLM-refined search term if available, otherwise raw query logic might fail
            term = params.get("search_term")
            if term:
                tool_input["query"] = term
            else:
                # Fallback: remove "search" keyword? No, just use original query relative to context if possible
                pass
                
        elif action == "list":
             tool_input["days"] = params.get("days_ago", 7)
             
        elif action == "read":
            if params.get("file_id"):
                tool_input["file_id"] = params.get("file_id")
            elif params.get("search_term"):
                 tool_input["query"] = params.get("search_term")
                 
        elif action == "extract_tasks":
            # For extraction, we pass the raw query or the text to process
            pass

        logger.info(f"[{self.name}] Action: {action}, Input: {tool_input}")
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_DRIVE, tool_input, f"accessing Google Drive ({action})"
        )
    
    def _extract_days(self, query: str) -> int:
        """Extract number of days from query like 'last 30 days' or 'past week'."""
        query_lower = query.lower()
        
        # Pattern: "last N days" or "past N days"
        match = re.search(DAYS_PATTERN_LAST, query_lower)
        if match:
            return int(match.group(1))
        
        # Pattern: "this week" or "past week" = 7 days
        if 'week' in query_lower:
            return 7
        
        # Pattern: "this month" or "past month" = 30 days
        if 'month' in query_lower:
            return 30
        
        # Default to 7 days
        return 7
