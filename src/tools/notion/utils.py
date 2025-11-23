"""
Notion Tool Utilities

Shared utility functions for Notion operations.
"""
from typing import Dict, Any, Optional, List


def extract_page_title(page: Dict[str, Any]) -> str:
    """
    Extract title from a Notion page object.
    
    Args:
        page: Notion page dictionary
        
    Returns:
        Page title or 'Untitled'
    """
    title_prop = page.get('properties', {}).get('title', {})
    if isinstance(title_prop, dict):
        title_array = title_prop.get('title', [])
        if title_array and isinstance(title_array, list):
            first_item = title_array[0]
            if isinstance(first_item, dict):
                return first_item.get('plain_text', 'Untitled')
    return 'Untitled'


def create_title_property(title: str) -> Dict[str, Any]:
    """
    Create a Notion title property from a string.
    
    Args:
        title: Title string
        
    Returns:
        Notion title property dictionary
    """
    return {
        'title': {
            'title': [
                {
                    'text': {
                        'content': title
                    }
                }
            ]
        }
    }


def format_page_url(page_id: str) -> str:
    """
    Format a Notion page URL from page ID.
    
    Args:
        page_id: Notion page ID
        
    Returns:
        Formatted URL
    """
    # Remove hyphens from page ID for URL
    page_id_clean = page_id.replace('-', '')
    return f"https://www.notion.so/{page_id_clean}"


def validate_database_id(database_id: str) -> bool:
    """
    Validate a Notion database ID format.
    
    Args:
        database_id: Database ID to validate
        
    Returns:
        True if valid format
    """
    # Notion IDs are 32 characters (UUID without hyphens)
    if not database_id:
        return False
    
    # Remove hyphens if present
    clean_id = database_id.replace('-', '')
    
    # Check length and alphanumeric
    return len(clean_id) == 32 and clean_id.isalnum()


def validate_page_id(page_id: str) -> bool:
    """
    Validate a Notion page ID format.
    
    Args:
        page_id: Page ID to validate
        
    Returns:
        True if valid format
    """
    return validate_database_id(page_id)  # Same format as database ID

