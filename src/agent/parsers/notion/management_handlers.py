"""
Notion Management Handlers - Handle Notion page and database management operations
"""
from typing import Dict, Any, Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionManagementHandlers:
    """Handles Notion page and database management operations"""
    
    def __init__(self, notion_parser):
        self.notion_parser = notion_parser
        self.llm_client = notion_parser.llm_client
        self.utility_handlers = notion_parser.utility_handlers
    
    def parse_and_update_page(self, tool: BaseTool, query: str) -> str:
        """
        Parse query and update Notion page
        
        Args:
            tool: NotionTool instance
            query: User query
            
        Returns:
            Update result string
        """
        logger.info(f"[NOTION] Parsing update page query: '{query}'")
        
        # Extract entities
        page_id = self.utility_handlers.extract_page_id_from_query(query)
        title = self.utility_handlers.extract_title_from_query(query)
        
        if not page_id:
            return "Error: Page ID is required to update a page. Please specify which page to update."
        
        return tool._run(
            action="update_page",
            page_id=page_id,
            title=title
        )
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """Handle search action"""
        search_query = self.utility_handlers.extract_search_query(query)
        database_id = self.utility_handlers.extract_database_id_from_query(query)
        
        if database_id:
            return tool._run(action="search", query=search_query, database_id=database_id)
        else:
            return tool._run(action="search", query=search_query)
    
    def handle_query_database_action(self, tool: BaseTool, query: str) -> str:
        """Handle database query action"""
        database_id = self.utility_handlers.extract_database_id_from_query(query)
        search_query = self.utility_handlers.extract_search_query(query)
        
        if not database_id:
            return "Error: Database ID is required to query a database."
        
        return tool._run(
            action="query_database",
            database_id=database_id,
            query=search_query
        )

