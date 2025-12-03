"""
Notion Query Processing Handlers - Query processing, execution and response generation

This module contains handlers for:
- Main query processing and execution
- LLM-enhanced classification
- Response generation with conversational formatting
- Validation and error handling
"""
import re
import json
from typing import Dict, Any, Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionQueryProcessingHandlers:
    """Handlers for query processing, execution and response generation"""
    
    def __init__(self, notion_parser):
        """Initialize with reference to main NotionParser"""
        self.notion_parser = notion_parser
        self.logger = logger
    
    def extract_actual_query(self, query: str) -> str:
        """
        Extract the actual user query from conversation context
        
        Args:
            query: Full query with conversation context
            
        Returns:
            Just the actual user query
        """
        # Look for "Current query:" pattern
        if "Current query:" in query:
            parts = query.split("Current query:")
            if len(parts) > 1:
                actual_query = parts[1].split("[Context:")[0].strip()
                return actual_query
        
        # Look for "User:" pattern (for conversation context)
        if "User:" in query:
            user_parts = query.split("User:")
            if len(user_parts) > 1:
                last_user_part = user_parts[-1]
                if "Assistant:" in last_user_part:
                    actual_query = last_user_part.split("Assistant:")[0].strip()
                else:
                    actual_query = last_user_part.strip()
                return actual_query
        
        return query
    
    def execute_notion_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any], action: str) -> str:
        """Execute Notion operation using LLM classification results"""
        logger.info(f"[NOTION] Executing with classification - Action: {action}")
        
        # Route to appropriate handler based on action
        if action == "create_page":
            return self.notion_parser.creation_handlers.parse_and_create_page(tool, query)
        elif action == "update_page":
            return self.notion_parser.management_handlers.parse_and_update_page(tool, query)
        elif action == "search":
            return self.notion_parser.management_handlers.handle_search_action(tool, query)
        elif action == "get_page":
            page_id = classification.get('page_id') or self.notion_parser.utility_handlers.extract_page_id_from_query(query)
            if page_id:
                return tool._run(action="get_page", page_id=page_id)
            else:
                return "Error: Page ID is required to retrieve a page."
        elif action == "query_database":
            return self.notion_parser.management_handlers.handle_query_database_action(tool, query)
        elif action == "cross_platform_synthesis":
            databases = classification.get('databases', [])
            return tool._run(action="cross_platform_synthesis", query=query, databases=databases)
        else:
            # Fallback to action handlers
            return self.notion_parser.action_handlers.handle_search_action(tool, query)

