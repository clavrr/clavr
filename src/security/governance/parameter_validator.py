"""
Parameter Validator for COR Layer

Provides strict type/format validation for all tool inputs before they reach external APIs.
"""
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, Callable
from src.utils.logger import setup_logger
from ..audit import SecurityAudit

logger = setup_logger(__name__)


# Common validation functions
def validate_email(value: str) -> bool:
    """Validate email format."""
    email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return bool(re.match(email_pattern, value))


def validate_iso_date(value: str) -> bool:
    """Validate ISO date string."""
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except (ValueError, AttributeError):
        return False


def validate_url(value: str) -> bool:
    """Validate URL format (basic check)."""
    url_pattern = r'^https?://[^\s<>"{}|\\^`\[\]]+$'
    return bool(re.match(url_pattern, value))


def validate_non_empty_string(value: str) -> bool:
    """Validate non-empty string."""
    return isinstance(value, str) and len(value.strip()) > 0


def validate_max_length(max_len: int) -> Callable[[str], bool]:
    """Factory: Validate string max length."""
    return lambda value: isinstance(value, str) and len(value) <= max_len


def validate_positive_int(value: Any) -> bool:
    """Validate positive integer."""
    return isinstance(value, int) and value > 0


# Schema definitions per tool action
# Format: {field_name: (validator_func, is_required, error_message)}
TOOL_SCHEMAS: Dict[str, Dict[str, tuple]] = {
    'email_send': {
        'to': (validate_email, True, "Invalid recipient email address"),
        'subject': (validate_max_length(500), True, "Subject too long (max 500 chars)"),
        'body': (validate_max_length(100000), True, "Email body too long"),
    },
    'calendar_create': {
        'summary': (validate_non_empty_string, True, "Event title cannot be empty"),
        'start_time': (validate_iso_date, True, "Invalid start time format"),
        'end_time': (validate_iso_date, False, "Invalid end time format"),
    },
    'task_create': {
        'title': (validate_max_length(1000), True, "Task title too long"),
        'due_date': (validate_iso_date, False, "Invalid due date format"),
    },
    'notion_create': {
        'title': (validate_non_empty_string, True, "Page title cannot be empty"),
    },
    'keep_create': {
        'title': (validate_max_length(1000), False, "Note title too long"),
        'text': (validate_max_length(50000), False, "Note text too long"),
    },
}


class ParameterValidator:
    """
    Validates tool parameters against predefined schemas.
    """
    
    _instance = None

    @classmethod
    def get_instance(cls) -> 'ParameterValidator':
        if cls._instance is None:
            cls._instance = ParameterValidator()
        return cls._instance
    
    def __init__(self, custom_schemas: Dict[str, Dict] = None):
        self._schemas = {**TOOL_SCHEMAS, **(custom_schemas or {})}
    
    def validate(
        self, 
        tool_name: str, 
        params: Dict[str, Any], 
        user_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Validate tool parameters against the schema.
        
        Args:
            tool_name: The tool/action being called
            params: The parameters to validate
            user_id: User ID for logging
            
        Returns:
            (is_valid, error_message)
        """
        schema = self._schemas.get(tool_name)
        
        if not schema:
            # No schema defined = allow (fail open for undefined tools)
            logger.debug(f"No validation schema for tool: {tool_name}")
            return True, ""
        
        errors = []
        
        for field_name, (validator, is_required, error_msg) in schema.items():
            value = params.get(field_name)
            
            # Check required fields
            if is_required and (value is None or value == ''):
                errors.append(f"Missing required field: {field_name}")
                continue
            
            # Skip validation for optional missing fields
            if value is None:
                continue
            
            # Run validator
            try:
                if not validator(value):
                    errors.append(error_msg)
            except Exception as e:
                errors.append(f"Validation error for {field_name}: {e}")
        
        if errors:
            # Log security event
            SecurityAudit.log_event(
                event_type="PARAMETER_VALIDATION_FAILED",
                status="REJECTED",
                severity="WARNING",
                user_id=user_id,
                details={
                    "tool": tool_name,
                    "errors": errors[:5],  # Limit logged errors
                    "param_keys": list(params.keys())
                }
            )
            
            logger.warning(f"Parameter validation failed for {tool_name}: {errors}")
            return False, "; ".join(errors)
        
        return True, ""
    
    def sanitize_params(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize parameters (strip whitespace, normalize formats).
        
        This is a lightweight sanitization, not a replacement for validation.
        """
        sanitized = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                # Strip whitespace
                sanitized[key] = value.strip()
            else:
                sanitized[key] = value
        
        return sanitized
