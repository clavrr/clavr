"""
Input Validation Utilities
Centralized validation for API inputs to prevent security vulnerabilities
"""
import re
from typing import Optional, List, Any
from fastapi import HTTPException, status

from ..logger import setup_logger

logger = setup_logger(__name__)


# ============================================
# VALIDATION CONSTANTS
# ============================================

class ValidationLimits:
    """Input validation limits"""
    
    # Text input limits
    QUERY_MAX_LENGTH = 10000  # User queries
    EMAIL_SUBJECT_MAX_LENGTH = 998  # RFC 2822 limit
    EMAIL_BODY_MAX_LENGTH = 1_000_000  # ~1MB for email body
    NAME_MAX_LENGTH = 255  # Names, titles
    DESCRIPTION_MAX_LENGTH = 5000  # Descriptions, summaries
    URL_MAX_LENGTH = 2048  # URLs
    
    # List limits
    MAX_RECIPIENTS = 100  # Email recipients
    MAX_SEARCH_RESULTS = 100  # Search results per page
    MAX_BATCH_SIZE = 1000  # Batch operations
    
    # Numeric limits
    MAX_PAGE_SIZE = 100  # Pagination
    MAX_TIMEOUT_SECONDS = 300  # 5 minutes
    MAX_RETRIES = 10
    
    # String pattern limits
    MAX_TAG_LENGTH = 50
    MAX_TAGS = 20


class DangerousPatterns:
    """Dangerous patterns to detect and block"""
    
    # SQL injection patterns
    SQL_INJECTION = [
        r';\s*(drop|delete|truncate|alter)',
        r'(union\s+select)',
        r'(insert\s+into)',
        r'(delete\s+from)',
        r'(drop\s+table)',
        r'(update\s+\w+\s+set)',
        r'(exec\s*\()',
        r'(execute\s*\()',
        r'--\s*$',  # SQL comment at end of line
        r'/\*.*\*/',  # SQL block comments
        r"'\s*(or|and)\s*'",  # ' OR ', ' AND '
        r"'\s*=\s*'",  # ' = '
    ]
    
    # Command injection patterns  
    COMMAND_INJECTION = [
        r';\s*(rm|del|format|mkfs)',
        r'\|\s*(nc|netcat|curl|wget)',
        r'&&\s*(whoami|id|uname)',
        r'`.*`',  # Backtick execution
        r'\$\(.*\)',  # Command substitution
    ]
    
    # Script injection patterns
    SCRIPT_INJECTION = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'on\w+\s*=',  # Event handlers (onclick, onerror, etc.)
        r'<iframe',
        r'<embed',
        r'<object',
    ]
    
    # Path traversal patterns
    PATH_TRAVERSAL = [
        r'\.\./+',  # ../ or ..\
        r'\.\.\\+',
        r'/etc/',
        r'/proc/',
        r'C:\\',
    ]


# ============================================
# VALIDATION FUNCTIONS
# ============================================

def validate_length(
    value: str,
    field_name: str,
    max_length: int,
    min_length: int = 0,
    allow_empty: bool = False
) -> str:
    """
    Validate string length
    
    Args:
        value: String to validate
        field_name: Name of the field (for error messages)
        max_length: Maximum allowed length
        min_length: Minimum allowed length (default: 0)
        allow_empty: Allow empty strings (default: False)
        
    Returns:
        Validated string
        
    Raises:
        HTTPException: If validation fails
    """
    if value is None:
        if allow_empty:
            return ""
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} is required"
        )
    
    length = len(value)
    
    if not allow_empty and length == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot be empty"
        )
    
    if length < min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be at least {min_length} characters (got {length})"
        )
    
    if length > max_length:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{field_name} exceeds maximum length of {max_length} characters (got {length})"
        )
    
    return value


def validate_no_dangerous_patterns(
    value: str,
    field_name: str,
    check_sql: bool = True,
    check_command: bool = True,
    check_script: bool = True,
    check_path: bool = True
) -> str:
    """
    Check for dangerous patterns (injection attacks)
    
    Args:
        value: String to validate
        field_name: Name of the field
        check_sql: Check for SQL injection patterns
        check_command: Check for command injection patterns
        check_script: Check for script injection patterns
        check_path: Check for path traversal patterns
        
    Returns:
        Validated string
        
    Raises:
        HTTPException: If dangerous pattern detected
    """
    if not value:
        return value
    
    value_lower = value.lower()
    
    # SQL injection check
    if check_sql:
        for pattern in DangerousPatterns.SQL_INJECTION:
            if re.search(pattern, value_lower, re.IGNORECASE):
                logger.warning(f"SQL injection pattern detected in {field_name}: {pattern}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid input detected in {field_name}"
                )
    
    # Command injection check
    if check_command:
        for pattern in DangerousPatterns.COMMAND_INJECTION:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Command injection pattern detected in {field_name}: {pattern}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid input detected in {field_name}"
                )
    
    # Script injection check (XSS)
    if check_script:
        for pattern in DangerousPatterns.SCRIPT_INJECTION:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Script injection pattern detected in {field_name}: {pattern}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid input detected in {field_name}"
                )
    
    # Path traversal check
    if check_path:
        for pattern in DangerousPatterns.PATH_TRAVERSAL:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Path traversal pattern detected in {field_name}: {pattern}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid input detected in {field_name}"
                )
    
    return value


def sanitize_text(value: str, preserve_newlines: bool = False) -> str:
    """
    Sanitize text input (remove excessive whitespace, normalize)
    
    Args:
        value: Text to sanitize
        preserve_newlines: Keep newline characters (default: False)
        
    Returns:
        Sanitized text
    """
    if not value:
        return ""
    
    # Trim leading/trailing whitespace
    value = value.strip()
    
    if preserve_newlines:
        # Normalize line endings
        value = re.sub(r'\r\n', '\n', value)
        # Remove excessive blank lines (more than 2 consecutive)
        value = re.sub(r'\n{3,}', '\n\n', value)
        # Remove trailing spaces on each line
        value = '\n'.join(line.rstrip() for line in value.split('\n'))
    else:
        # Replace all whitespace with single space
        value = re.sub(r'\s+', ' ', value)
    
    return value


def validate_email_address(email: str) -> str:
    """
    Validate email address format
    
    Args:
        email: Email address to validate
        
    Returns:
        Validated email
        
    Raises:
        HTTPException: If email format invalid
    """
    if not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email address is required"
        )
    
    # Basic email regex (RFC 5322 simplified)
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address format"
        )
    
    if len(email) > 320:  # RFC 5321 limit
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email address too long (max 320 characters)"
        )
    
    return email.lower()


def validate_url(url: str, allow_relative: bool = False) -> str:
    """
    Validate URL format
    
    Args:
        url: URL to validate
        allow_relative: Allow relative URLs (default: False)
        
    Returns:
        Validated URL
        
    Raises:
        HTTPException: If URL format invalid
    """
    if not url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL is required"
        )
    
    if len(url) > ValidationLimits.URL_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"URL too long (max {ValidationLimits.URL_MAX_LENGTH} characters)"
        )
    
    # Check for valid URL format
    if not allow_relative:
        url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        if not re.match(url_pattern, url, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid URL format (must start with http:// or https://)"
            )
    
    # Check for dangerous protocols
    dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
    for protocol in dangerous_protocols:
        if url.lower().startswith(protocol):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dangerous URL protocol detected"
            )
    
    return url


def validate_list_length(
    items: List[Any],
    field_name: str,
    max_length: int,
    min_length: int = 0,
    allow_empty: bool = True
) -> List[Any]:
    """
    Validate list length
    
    Args:
        items: List to validate
        field_name: Name of the field
        max_length: Maximum list length
        min_length: Minimum list length (default: 0)
        allow_empty: Allow empty lists (default: True)
        
    Returns:
        Validated list
        
    Raises:
        HTTPException: If validation fails
    """
    if items is None:
        if allow_empty:
            return []
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} is required"
        )
    
    length = len(items)
    
    if not allow_empty and length == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot be empty"
        )
    
    if length < min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must have at least {min_length} items (got {length})"
        )
    
    if length > max_length:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{field_name} exceeds maximum length of {max_length} items (got {length})"
        )
    
    return items


def validate_integer_range(
    value: int,
    field_name: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None
) -> int:
    """
    Validate integer is within range
    
    Args:
        value: Integer to validate
        field_name: Name of the field
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        Validated integer
        
    Raises:
        HTTPException: If validation fails
    """
    if min_value is not None and value < min_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be at least {min_value} (got {value})"
        )
    
    if max_value is not None and value > max_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be at most {max_value} (got {value})"
        )
    
    return value


# ============================================
# VALIDATION HELPERS
# ============================================

def validate_query_input(query: str) -> str:
    """
    Comprehensive validation for user query inputs
    
    Combines length validation, sanitization, and security checks
    
    Args:
        query: User query string
        
    Returns:
        Validated and sanitized query
    """
    # Check length
    query = validate_length(
        query,
        "query",
        max_length=ValidationLimits.QUERY_MAX_LENGTH,
        min_length=1,
        allow_empty=False
    )
    
    # Sanitize
    query = sanitize_text(query, preserve_newlines=False)
    
    # Check for dangerous patterns
    query = validate_no_dangerous_patterns(
        query,
        "query",
        check_sql=True,
        check_command=False,  # Allow shell-like syntax in queries
        check_script=True,
        check_path=False  # Allow file paths in queries
    )
    
    return query


def validate_email_body(body: str) -> str:
    """
    Validate email body content
    
    Args:
        body: Email body text
        
    Returns:
        Validated email body
    """
    body = validate_length(
        body,
        "email body",
        max_length=ValidationLimits.EMAIL_BODY_MAX_LENGTH,
        allow_empty=True
    )
    
    # Preserve newlines in email body
    body = sanitize_text(body, preserve_newlines=True)
    
    # Don't check for script injection (emails may contain HTML)
    # But check for SQL and command injection
    body = validate_no_dangerous_patterns(
        body,
        "email body",
        check_sql=True,
        check_command=True,
        check_script=False,  # Allow HTML in emails
        check_path=False
    )
    
    return body

def validate_request_size(max_size_mb: float = 10):
    """
    Decorator to validate request body size
    
    Usage:
        @router.post("/upload")
        @validate_request_size(max_size_mb=5)
        async def upload_file(request: Request):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Check content-length header
            request = kwargs.get('request')
            if request:
                content_length = request.headers.get('content-length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    if size_mb > max_size_mb:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Request body too large (max {max_size_mb}MB)"
                        )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
