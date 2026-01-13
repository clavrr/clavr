"""
Input Sanitization Utilities

Provides functions for sanitizing user input to prevent XSS, SQL injection,
and other injection attacks.
"""
import re
import html
from typing import Optional, List, Dict, Any
from functools import lru_cache

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Try to import bleach for HTML sanitization
try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False
    logger.warning("bleach package not installed - using basic HTML sanitization")


# Allowed HTML tags for rich text content
ALLOWED_TAGS = [
    'p', 'br', 'span', 'div',
    'strong', 'b', 'em', 'i', 'u', 's', 'strike',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'a', 'img',
    'blockquote', 'pre', 'code',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr',
]

# Allowed HTML attributes
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id', 'style'],
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}

# Allowed URL schemes
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto', 'tel']

# Dangerous patterns to remove
DANGEROUS_PATTERNS = [
    r'javascript:',
    r'vbscript:',
    r'data:text/html',
    r'on\w+\s*=',  # Event handlers like onclick, onerror
    r'<script[^>]*>.*?</script>',
    r'<iframe[^>]*>.*?</iframe>',
    r'<object[^>]*>.*?</object>',
    r'<embed[^>]*>',
    r'<link[^>]*>',
    r'<meta[^>]*>',
    r'<base[^>]*>',
]


def sanitize_html(
    content: str,
    allowed_tags: Optional[List[str]] = None,
    allowed_attributes: Optional[Dict[str, List[str]]] = None,
    strip: bool = True
) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.
    
    Args:
        content: HTML content to sanitize
        allowed_tags: List of allowed HTML tags (default: ALLOWED_TAGS)
        allowed_attributes: Dict of allowed attributes per tag
        strip: If True, strip disallowed tags; if False, escape them
        
    Returns:
        Sanitized HTML content
    """
    if not content:
        return content
    
    allowed_tags = allowed_tags or ALLOWED_TAGS
    allowed_attributes = allowed_attributes or ALLOWED_ATTRIBUTES
    
    if BLEACH_AVAILABLE:
        # Use bleach for comprehensive sanitization
        cleaned = bleach.clean(
            content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=ALLOWED_PROTOCOLS,
            strip=strip
        )
        return cleaned
    else:
        # Basic sanitization fallback
        return _basic_html_sanitize(content, strip)


def _basic_html_sanitize(content: str, strip: bool = True) -> str:
    """
    Basic HTML sanitization without bleach.
    
    This is a fallback and is less secure than bleach.
    """
    # Remove dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE | re.DOTALL)
    
    if strip:
        # Remove all script, style, and other dangerous tags entirely
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<iframe[^>]*>.*?</iframe>', '', content, flags=re.IGNORECASE | re.DOTALL)
    
    return content


def sanitize_string(
    text: str,
    max_length: Optional[int] = None,
    allow_newlines: bool = True
) -> str:
    """
    Sanitize a plain text string.
    
    Args:
        text: Text to sanitize
        max_length: Maximum allowed length (truncates if exceeded)
        allow_newlines: Whether to preserve newlines
        
    Returns:
        Sanitized text
    """
    if not text:
        return text
    
    # Escape HTML entities
    text = html.escape(text)
    
    # Optionally remove newlines
    if not allow_newlines:
        text = text.replace('\n', ' ').replace('\r', '')
    
    # Truncate if max_length specified
    if max_length and len(text) > max_length:
        text = text[:max_length]
    
    # Remove null bytes and other control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    return text.strip()


def sanitize_email(email: str) -> Optional[str]:
    """
    Validate and sanitize an email address.
    
    Args:
        email: Email address to validate
        
    Returns:
        Sanitized email or None if invalid
    """
    if not email:
        return None
    
    email = email.strip().lower()
    
    # Basic email regex pattern
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if re.match(email_pattern, email):
        return email
    
    return None


def sanitize_url(url: str, allowed_protocols: Optional[List[str]] = None) -> Optional[str]:
    """
    Validate and sanitize a URL.
    
    Args:
        url: URL to validate
        allowed_protocols: List of allowed protocols (default: http, https)
        
    Returns:
        Sanitized URL or None if invalid
    """
    if not url:
        return None
    
    url = url.strip()
    allowed_protocols = allowed_protocols or ['http', 'https']
    
    # Check for dangerous schemes
    for pattern in ['javascript:', 'vbscript:', 'data:']:
        if url.lower().startswith(pattern):
            logger.warning(f"Blocked dangerous URL scheme: {pattern}")
            return None
    
    # Verify protocol
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        if parsed.scheme not in allowed_protocols:
            return None
        if not parsed.netloc:
            return None
        return url
    except Exception:
        return None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal attacks.
    
    Args:
        filename: Filename to sanitize
        
    Returns:
        Safe filename
    """
    if not filename:
        return "unnamed"
    
    # Remove path components
    filename = filename.replace('/', '_').replace('\\', '_')
    
    # Remove null bytes
    filename = filename.replace('\x00', '')
    
    # Remove or replace dangerous characters
    filename = re.sub(r'[<>:"|?*]', '_', filename)
    
    # Prevent hidden files
    filename = filename.lstrip('.')
    
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')
    
    return filename or "unnamed"


def sanitize_sql_identifier(identifier: str) -> str:
    """
    Sanitize a SQL identifier (table name, column name).
    
    WARNING: This should rarely be needed. Use parameterized queries instead.
    
    Args:
        identifier: SQL identifier to sanitize
        
    Returns:
        Safe identifier
    """
    if not identifier:
        raise ValueError("SQL identifier cannot be empty")
    
    # Only allow alphanumeric and underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', identifier)
    
    # Must start with letter or underscore
    if sanitized and not re.match(r'^[a-zA-Z_]', sanitized):
        sanitized = '_' + sanitized
    
    if not sanitized:
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    
    return sanitized


def sanitize_dict(
    data: Dict[str, Any],
    string_max_length: int = 10000,
    recursive: bool = True
) -> Dict[str, Any]:
    """
    Recursively sanitize all string values in a dictionary.
    
    Args:
        data: Dictionary to sanitize
        string_max_length: Max length for string values
        recursive: Whether to process nested dicts
        
    Returns:
        Sanitized dictionary
    """
    sanitized = {}
    
    for key, value in data.items():
        # Sanitize key
        safe_key = sanitize_string(str(key), max_length=256, allow_newlines=False)
        
        if isinstance(value, str):
            sanitized[safe_key] = sanitize_string(value, max_length=string_max_length)
        elif isinstance(value, dict) and recursive:
            sanitized[safe_key] = sanitize_dict(value, string_max_length, recursive)
        elif isinstance(value, list):
            sanitized[safe_key] = [
                sanitize_string(str(v), max_length=string_max_length) if isinstance(v, str)
                else sanitize_dict(v, string_max_length, recursive) if isinstance(v, dict)
                else v
                for v in value
            ]
        else:
            sanitized[safe_key] = value
    
    return sanitized


# Pydantic validator helpers
def create_html_sanitizer(
    allowed_tags: Optional[List[str]] = None,
    max_length: Optional[int] = None
):
    """
    Create a Pydantic validator for HTML content.
    
    Usage:
        class MyModel(BaseModel):
            content: str
            
            _sanitize_content = validator('content', allow_reuse=True)(
                create_html_sanitizer(max_length=50000)
            )
    """
    def validator_func(cls, v):
        if v is None:
            return v
        sanitized = sanitize_html(v, allowed_tags=allowed_tags)
        if max_length and len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        return sanitized
    
    return validator_func


def create_string_sanitizer(
    max_length: Optional[int] = None,
    allow_newlines: bool = True
):
    """
    Create a Pydantic validator for plain text.
    
    Usage:
        class MyModel(BaseModel):
            title: str
            
            _sanitize_title = validator('title', allow_reuse=True)(
                create_string_sanitizer(max_length=500)
            )
    """
    def validator_func(cls, v):
        if v is None:
            return v
        return sanitize_string(v, max_length=max_length, allow_newlines=allow_newlines)
    
    return validator_func
