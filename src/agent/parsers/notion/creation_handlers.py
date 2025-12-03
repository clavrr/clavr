"""
Notion Creation Handlers - Handle Notion page and database entry creation
"""
import re
from typing import Dict, Any, Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import NotionParserConfig

logger = setup_logger(__name__)


class NotionCreationHandlers:
    """Handles Notion page and database entry creation"""
    
    def __init__(self, notion_parser):
        self.notion_parser = notion_parser
        self.llm_client = notion_parser.llm_client
        self.utility_handlers = notion_parser.utility_handlers
    
    def parse_and_create_page(self, tool: BaseTool, query: str) -> str:
        """
        Parse query and create Notion page
        
        Args:
            tool: NotionTool instance
            query: User query
            
        Returns:
            Creation result string
        """
        logger.info(f"[NOTION] Parsing create page query: '{query}'")
        
        # Extract entities
        title = self.utility_handlers.extract_title_from_query(query)
        database_id = self.utility_handlers.extract_database_id_from_query(query)
        
        # Extract content from query
        content = self._extract_content_from_query(query)
        
        # Use LLM to enhance title if not extracted
        if not title and self.llm_client:
            title = self._generate_title_with_llm(query)
        
        # Validate required fields
        if not database_id:
            return "Error: Database ID is required to create a page. Please specify which database to add the page to."
        
        # Create page
        return tool._run(
            action="create_page",
            database_id=database_id,
            title=title,
            content=content
        )
    
    def _extract_content_from_query(self, query: str) -> Optional[str]:
        """Extract content description from query"""
        # Look for "about" or "for" patterns
        about_match = re.search(r'(?:about|for|regarding)\s+(.+?)(?:\s+in|\s+with|\s+using|$)', query, re.IGNORECASE)
        if about_match:
            content = about_match.group(1).strip()
            # Remove title if it appears in content
            title = self.utility_handlers.extract_title_from_query(query)
            if title and title.lower() in content.lower():
                content = content.replace(title, '').strip()
            return content if content else None
        
        return None
    
    def _generate_title_with_llm(self, query: str) -> Optional[str]:
        """Generate page title using LLM"""
        if not self.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            
            from ....ai.prompts import NOTION_TITLE_GENERATION_PROMPT
            from ....ai.prompts.utils import format_prompt
            
            prompt = format_prompt(NOTION_TITLE_GENERATION_PROMPT, query=query)
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            title = response.content if hasattr(response, 'content') else str(response)
            title = title.strip().strip('"').strip("'")
            
            if self.utility_handlers.validate_title(title):
                logger.info(f"[NOTION] LLM generated title: '{title}'")
                return title
        except Exception as e:
            logger.debug(f"[NOTION] LLM title generation failed: {e}")
        
        return None
    
    def parse_and_create_database_entry(self, tool: BaseTool, query: str) -> str:
        """
        Parse query and create database entry
        
        Args:
            tool: NotionTool instance
            query: User query
            
        Returns:
            Creation result string
        """
        logger.info(f"[NOTION] Parsing create database entry query: '{query}'")
        
        # Extract entities
        database_id = self.utility_handlers.extract_database_id_from_query(query)
        properties = self._extract_properties_from_query(query)
        
        if not database_id:
            return "Error: Database ID is required to create a database entry."
        
        return tool._run(
            action="create_database_entry",
            database_id=database_id,
            properties=properties
        )
    
    def _extract_properties_from_query(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract properties from query"""
        # This would use LLM to extract structured properties
        # For now, return None (properties would be extracted by NotionService)
        return None

