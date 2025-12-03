"""
Notion Utility Handlers - Common utility functions and helpers

This module contains handlers for:
- Notion parsing from results
- Response formatting
- Validation helpers
- Common extraction utilities
"""
import re
import json
from typing import Dict, Any, Optional, List

from ....utils.logger import setup_logger
from .constants import NotionParserConfig

logger = setup_logger(__name__)


class NotionUtilityHandlers:
    """Handlers for common utility functions and helpers"""
    
    def __init__(self, notion_parser):
        """Initialize with reference to main NotionParser"""
        self.notion_parser = notion_parser
        self.logger = logger
    
    def extract_title_from_query(self, query: str) -> Optional[str]:
        """
        Extract page title from natural language query
        
        Args:
            query: User query
            
        Returns:
            Extracted title or None
        """
        query_lower = query.lower()
        
        # Patterns for title extraction
        title_patterns = [
            r'(?:title|named|called|titled)\s+(?:is|as|:)?\s*["\']([^"\']+)["\']',
            r'(?:title|named|called|titled)\s+(?:is|as|:)?\s*([A-Z][^.!?]+?)(?:\s+about|\s+for|$)',
            r'create\s+(?:a|an)?\s*(?:page|notion)?\s*(?:named|called|titled)?\s*["\']([^"\']+)["\']',
            r'create\s+(?:a|an)?\s*(?:page|notion)?\s*(?:named|called|titled)?\s*([A-Z][^.!?]+?)(?:\s+about|\s+for|$)',
        ]
        
        for pattern in title_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if len(title) >= NotionParserConfig.MIN_TITLE_LENGTH:
                    return title
        
        # Fallback: extract after "about" or "for"
        about_match = re.search(r'(?:about|for)\s+(.+?)(?:\s+in|\s+with|\s+using|$)', query, re.IGNORECASE)
        if about_match:
            potential_title = about_match.group(1).strip()
            # Clean up common trailing words
            potential_title = re.sub(r'\s+(?:page|notion|database)$', '', potential_title, flags=re.IGNORECASE)
            if len(potential_title) >= NotionParserConfig.MIN_TITLE_LENGTH:
                return potential_title
        
        return None
    
    def extract_database_id_from_query(self, query: str) -> Optional[str]:
        """
        Extract database ID from query (if mentioned)
        
        Args:
            query: User query
            
        Returns:
            Database ID or None
        """
        # Look for UUID pattern (Notion IDs are UUIDs)
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        match = re.search(uuid_pattern, query, re.IGNORECASE)
        if match:
            return match.group(0)
        
        # Look for database name patterns
        db_patterns = [
            r'(?:in|to|from|using)\s+(?:the\s+)?(?:database|db)\s+(?:named|called)?\s*["\']([^"\']+)["\']',
            r'(?:in|to|from|using)\s+(?:the\s+)?(?:database|db)\s+(?:named|called)?\s*([A-Z][a-zA-Z\s]+?)(?:\s+for|\s+about|$)',
        ]
        
        for pattern in db_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                db_name = match.group(1).strip()
                # Return as-is (actual ID lookup would be done by NotionService)
                return db_name
        
        return None
    
    def extract_page_id_from_query(self, query: str) -> Optional[str]:
        """
        Extract page ID from query (if mentioned)
        
        Args:
            query: User query
            
        Returns:
            Page ID or None
        """
        # Look for UUID pattern
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        match = re.search(uuid_pattern, query, re.IGNORECASE)
        if match:
            return match.group(0)
        
        # Look for page name patterns
        page_patterns = [
            r'(?:page|notion)\s+(?:named|called|titled)?\s*["\']([^"\']+)["\']',
            r'(?:the|this)\s+(?:page|notion)\s+(?:named|called|titled)?\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in page_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                page_name = match.group(1).strip()
                # Return as-is (actual ID lookup would be done by NotionService)
                return page_name
        
        return None
    
    def extract_search_query(self, query: str) -> str:
        """
        Extract search query from natural language
        
        Args:
            query: User query
            
        Returns:
            Search query string
        """
        # Remove action words
        query_lower = query.lower()
        action_removed = re.sub(
            r'^(?:search|find|look\s+for|query|get|show|list)\s+(?:in\s+)?(?:notion|my\s+notion|the\s+notion)?\s*',
            '',
            query_lower,
            flags=re.IGNORECASE
        )
        
        # Remove common trailing phrases
        cleaned = re.sub(
            r'\s+(?:in\s+notion|from\s+notion|on\s+notion|using\s+notion)$',
            '',
            action_removed,
            flags=re.IGNORECASE
        )
        
        return cleaned.strip() if cleaned.strip() else query
    
    def validate_title(self, title: Optional[str]) -> bool:
        """Validate page title"""
        if not title:
            return False
        return NotionParserConfig.MIN_TITLE_LENGTH <= len(title) <= NotionParserConfig.MAX_TITLE_LENGTH
    
    def validate_database_id(self, database_id: Optional[str]) -> bool:
        """Validate database ID format"""
        if not database_id:
            return False
        # Check if it's a UUID or a valid identifier
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, database_id, re.IGNORECASE)) or len(database_id) > 0
    
    def validate_page_id(self, page_id: Optional[str]) -> bool:
        """Validate page ID format"""
        if not page_id:
            return False
        # Check if it's a UUID or a valid identifier
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, page_id, re.IGNORECASE)) or len(page_id) > 0
    
    def format_page_result(self, page_data: Dict[str, Any]) -> str:
        """Format page data for display"""
        title = page_data.get('title', 'Untitled')
        url = page_data.get('url', '')
        created = page_data.get('created_time', '')
        
        result = f"**{title}**"
        if url:
            result += f"\nURL: {url}"
        if created:
            result += f"\nCreated: {created}"
        
        return result
    
    def format_search_results(self, results: List[Dict[str, Any]]) -> str:
        """Format search results for display"""
        if not results:
            return "No results found."
        
        formatted = []
        for i, result in enumerate(results[:NotionParserConfig.MAX_PAGES_DISPLAY], 1):
            formatted.append(f"{i}. {self.format_page_result(result)}")
        
        if len(results) > NotionParserConfig.MAX_PAGES_DISPLAY:
            formatted.append(f"\n... and {len(results) - NotionParserConfig.MAX_PAGES_DISPLAY} more results")
        
        return "\n\n".join(formatted)

