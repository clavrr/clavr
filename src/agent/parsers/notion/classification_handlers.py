"""
Notion Classification Handlers - Handle Notion query classification and intent detection

Integrates with LLM for semantic understanding of Notion queries.
"""
import re
import json
from typing import Dict, Any, Optional, List

from ....utils.logger import setup_logger
from .constants import NotionParserConfig, NotionActionTypes

logger = setup_logger(__name__)


class NotionClassificationHandlers:
    """Handles Notion query classification, intent detection, and routing logic"""
    
    def __init__(self, notion_parser):
        self.notion_parser = notion_parser
        self.llm_client = notion_parser.llm_client
    
    def detect_notion_action(self, query: str) -> str:
        """
        Detect what Notion action the user wants to perform using LLM-based semantic understanding
        
        Args:
            query: User query
            
        Returns:
            Detected action (e.g., 'search', 'create_page', 'update_page', etc.)
        """
        query_lower = query.lower().strip()
        logger.info(f"[NOTION] Detecting action for query: '{query}'")
        
        # PRIORITY 1: Use LLM for semantic understanding FIRST
        if self.notion_parser.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                from ....ai.prompts import NOTION_CLASSIFICATION_PROMPT
                from ....ai.prompts.utils import format_prompt
                
                prompt = format_prompt(NOTION_CLASSIFICATION_PROMPT, query=query)

                response = self.notion_parser.llm_client.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    action = result.get('action')
                    confidence = result.get('confidence', 0.7)
                    
                    if action and confidence >= 0.7:
                        logger.info(f"[NOTION] LLM detected action: '{query}' → {action} (confidence: {confidence})")
                        return action
            except Exception as e:
                logger.debug(f"[NOTION] LLM detection failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based detection
        query_lower = query.lower()
        
        # Create page patterns
        if any(word in query_lower for word in ['create', 'add', 'new', 'make', 'write']):
            if 'page' in query_lower or 'notion' in query_lower:
                return NotionActionTypes.CREATE_PAGE
            elif 'database' in query_lower and 'entry' in query_lower:
                return NotionActionTypes.CREATE_DATABASE_ENTRY
        
        # Update patterns
        if any(word in query_lower for word in ['update', 'edit', 'change', 'modify', 'revise']):
            if 'page' in query_lower:
                return NotionActionTypes.UPDATE_PAGE
            elif 'database' in query_lower:
                return NotionActionTypes.UPDATE_DATABASE_ENTRY
        
        # Search patterns
        if any(word in query_lower for word in ['search', 'find', 'look for', 'query', 'get']):
            if 'database' in query_lower:
                return NotionActionTypes.QUERY_DATABASE
            else:
                return NotionActionTypes.SEARCH
        
        # Get page patterns
        if any(word in query_lower for word in ['get', 'show', 'retrieve', 'fetch', 'display']):
            if 'page' in query_lower:
                return NotionActionTypes.GET_PAGE
        
        # Cross-platform synthesis patterns
        if any(word in query_lower for word in ['synthesize', 'combine', 'merge', 'integrate']):
            return NotionActionTypes.CROSS_PLATFORM_SYNTHESIS
        
        # Auto-manage patterns
        if any(word in query_lower for word in ['auto', 'automatically', 'sync', 'manage']):
            return NotionActionTypes.AUTO_MANAGE_DATABASE
        
        # Default to search if Notion-related keywords present
        if any(word in query_lower for word in ['notion', 'page', 'database']):
            return NotionActionTypes.SEARCH
        
        # Default action
        return NotionActionTypes.SEARCH
    
    def classify_notion_query(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Classify Notion query using LLM if available
        
        Args:
            query: User query
            
        Returns:
            Classification dictionary or None
        """
        if not self.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            from ....ai.prompts import NOTION_ENTITY_EXTRACTION_PROMPT
            from ....ai.prompts.utils import format_prompt
            
            prompt = format_prompt(NOTION_ENTITY_EXTRACTION_PROMPT, query=query)
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            logger.debug(f"[NOTION] LLM classification failed: {e}")
        
        return None

