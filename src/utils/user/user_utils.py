"""
User utility functions for personalization
"""
from typing import Optional
import re

def extract_first_name(user_name: Optional[str], user_email: Optional[str] = None) -> Optional[str]:
    """
    Extract first name from user's full name or email address.
    
    Args:
        user_name: User's full name (e.g., "Maniko Anthony" or "Anthony Maniko")
        user_email: User's email address (e.g., "manikoa@whitman.edu")
        
    Returns:
        First name (e.g., "Maniko") or None if not available
    """
    # Try to extract from full name first
    if user_name:
        # Split by space and take first part
        name_parts = user_name.strip().split()
        if name_parts:
            first_name = name_parts[0]
            # Capitalize first letter only (preserve casing like "Maniko")
            if first_name:
                return first_name.capitalize()
    
    # Fallback: extract from email if name not available
    if user_email:
        # Extract local part before @
        local_part = user_email.split('@')[0] if '@' in user_email else user_email
        
        # Remove common email prefixes/suffixes
        local_part = re.sub(r'[._-]', ' ', local_part)  # Replace dots/underscores/dashes with spaces
        
        # Take first part
        name_parts = local_part.split()
        if name_parts:
            first_name = name_parts[0]
            # Capitalize first letter
            if first_name:
                return first_name.capitalize()
    
    return None

