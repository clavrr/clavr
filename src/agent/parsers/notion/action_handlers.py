"""
Notion Action Handlers - Handle specific Notion actions
"""
from typing import Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import NotionActionTypes

logger = setup_logger(__name__)


class NotionActionHandlers:
    """Handles specific Notion actions and operations"""
    
    def __init__(self, notion_parser):
        self.notion_parser = notion_parser
        self.llm_client = notion_parser.llm_client
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """Handle Notion search action"""
        return tool._run(action="search", query=query)
    
    def handle_create_page_action(self, tool: BaseTool, query: str) -> str:
        """Handle Notion page creation action"""
        return self.notion_parser.creation_handlers.parse_and_create_page(tool, query)
    
    def handle_update_page_action(self, tool: BaseTool, query: str) -> str:
        """Handle Notion page update action"""
        return self.notion_parser.management_handlers.parse_and_update_page(tool, query)
    
    def handle_get_page_action(self, tool: BaseTool, query: str) -> str:
        """Handle Notion page retrieval action"""
        page_id = self.notion_parser.utility_handlers.extract_page_id_from_query(query)
        if page_id:
            return tool._run(action="get_page", page_id=page_id)
        else:
            return tool._run(action="get_page", query=query)
    
    def handle_query_database_action(self, tool: BaseTool, query: str) -> str:
        """Handle Notion database query action"""
        database_id = self.notion_parser.utility_handlers.extract_database_id_from_query(query)
        if database_id:
            search_query = self.notion_parser.utility_handlers.extract_search_query(query)
            return tool._run(action="query_database", database_id=database_id, query=search_query)
        else:
            return tool._run(action="query_database", query=query)
    
    def handle_cross_platform_synthesis_action(self, tool: BaseTool, query: str) -> str:
        """Handle cross-platform synthesis action"""
        return tool._run(action="cross_platform_synthesis", query=query)
    
    def handle_auto_manage_database_action(self, tool: BaseTool, query: str) -> str:
        """Handle auto-manage database action"""
        return tool._run(action="auto_manage_database", query=query)

