"""
Email Utilities - Centralized utility functions for email operations

Consolidates common functionality to avoid duplication and improve maintainability.
"""
from typing import Dict, Any, Optional, List
import base64

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


# ============================================================================
# MESSAGE EXTRACTION AND FORMATTING
# ============================================================================

def extract_headers(headers: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Extract headers from Gmail API response into a dictionary.
    
    Args:
        headers: List of header dictionaries from Gmail API (format: [{'name': '...', 'value': '...'}])
        
    Returns:
        Dictionary mapping header names to values
    """
    return {h['name']: h['value'] for h in headers}


def extract_message_body(payload: Dict[str, Any]) -> str:
    """
    Extract message body from Gmail message payload.
    
    Handles both multipart and single-part messages, preferring plain text over HTML.
    
    Args:
        payload: Gmail message payload dictionary
        
    Returns:
        Extracted message body text (empty string if extraction fails)
    """
    try:
        body = ""
        
        # Check if it's a multipart message
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        body += base64.urlsafe_b64decode(data).decode('utf-8')
                elif part['mimeType'] == 'text/html' and not body:
                    # Fallback to HTML if no plain text found
                    data = part['body'].get('data', '')
                    if data:
                        body += base64.urlsafe_b64decode(data).decode('utf-8')
        else:
            # Single part message
            if payload.get('mimeType') == 'text/plain':
                data = payload.get('body', {}).get('data', '')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8')
        
        return body.strip()
        
    except Exception as e:
        logger.warning(f"Failed to extract message body: {e}")
        return ""


def get_header_value(header_dict: Dict[str, str], key: str, default: str = '') -> str:
    """Get header value case-insensitively"""
    # Try exact match first
    if key in header_dict:
        return header_dict[key]
    
    # Try case-insensitive extraction
    key_lower = key.lower()
    for k, v in header_dict.items():
        if k.lower() == key_lower:
            return v
    return default

def format_message_from_gmail(
    message: Dict[str, Any],
    include_internal_date: bool = False
) -> Dict[str, Any]:
    """
    Format a Gmail API message response into a standardized dictionary.
    
    Args:
        message: Gmail API message dictionary
        include_internal_date: Whether to include internal_date field (for sorting)
        
    Returns:
        Formatted message dictionary with standardized fields
    """
    # Extract headers
    headers = message.get('payload', {}).get('headers', [])
    header_dict = extract_headers(headers)
    
    # Extract body
    body = extract_message_body(message.get('payload', {}))
    
    # Build formatted message
    formatted = {
        'id': message.get('id', ''),
        'thread_id': message.get('threadId'),
        'subject': get_header_value(header_dict, 'Subject', 'No Subject'),
        'sender': get_header_value(header_dict, 'From', 'Unknown'),
        'recipient': get_header_value(header_dict, 'To', ''),
        'date': get_header_value(header_dict, 'Date', ''),
        'body': body,
        'labels': message.get('labelIds', []),
        'snippet': message.get('snippet', ''),
        'size_estimate': message.get('sizeEstimate', 0)
    }
    
    # Add internal_date if requested (for sorting)
    if include_internal_date:
        formatted['internal_date'] = message.get('internalDate', 0)
    
    return formatted


# ============================================================================
# MESSAGE CREATION
# ============================================================================

def create_gmail_message(
    to: str,
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    Create a Gmail message object in RFC 2822 format.
    
    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        cc: Optional CC recipients
        bcc: Optional BCC recipients
        
    Returns:
        Gmail API message dictionary with 'raw' field (base64-encoded)
    """
    # Build RFC 2822 message
    message_lines = [f"To: {to}"]
    
    if cc:
        message_lines.append(f"Cc: {', '.join(cc)}")
    if bcc:
        message_lines.append(f"Bcc: {', '.join(bcc)}")
    
    message_lines.extend([
        f"Subject: {subject}",
        "Content-Type: text/plain; charset=utf-8",
        "",  # Empty line separating headers from body
        body
    ])
    
    message = "\r\n".join(message_lines)
    
    # Encode to base64url format
    raw_message = base64.urlsafe_b64encode(message.encode('utf-8')).decode('utf-8')
    
    return {'raw': raw_message}

