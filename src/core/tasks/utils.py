"""
Task Utilities - Centralized utility functions for task operations

Consolidates common functionality to avoid duplication and improve maintainability.
Similar to core/email/utils.py and core/calendar/utils.py structure.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import json

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


# ============================================================================
# JSON STORAGE UTILITIES
# ============================================================================

def load_json_file(file_path: Path, default_value: List = None) -> List[Dict[str, Any]]:
    """
    Load data from a JSON file with error handling.
    
    Args:
        file_path: Path to JSON file
        default_value: Default value to return if file doesn't exist or fails to load
        
    Returns:
        Loaded data (list of dictionaries) or default_value
    """
    if default_value is None:
        default_value = []
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        logger.debug(f"File not found: {file_path}, returning default")
        return default_value
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from {file_path}: {e}")
        return default_value
    except Exception as e:
        logger.warning(f"Failed to load {file_path}: {e}")
        return default_value


def save_json_file(file_path: Path, data: List[Dict[str, Any]], indent: int = 2) -> None:
    """
    Save data to a JSON file with error handling.
    
    Args:
        file_path: Path to JSON file
        data: Data to save (list of dictionaries)
        indent: JSON indentation level
        
    Raises:
        Exception: If save fails
    """
    try:
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=indent)
    except Exception as e:
        logger.error(f"Failed to save {file_path}: {e}")
        raise


# ============================================================================
# DATE/TIME UTILITIES
# ============================================================================

def parse_task_date(date_str: Optional[str]) -> Optional[str]:
    """
    Parse and normalize a task date string to ISO format.
    
    Handles various date formats and ensures consistent ISO format output.
    
    Args:
        date_str: Date string (ISO format, datetime object, or None)
        
    Returns:
        ISO format date string or None
    """
    if not date_str:
        return None
    
    try:
        if isinstance(date_str, datetime):
            return date_str.isoformat()
        
        # Handle ISO format strings
        if isinstance(date_str, str):
            # Normalize timezone format
            normalized = date_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(normalized)
            return dt.isoformat()
        
        return None
    except Exception as e:
        logger.debug(f"Failed to parse date '{date_str}': {e}")
        return date_str  # Return original if parsing fails


def parse_task_datetime(date_str: str, default_tz: Optional[Any] = None) -> Optional[datetime]:
    """
    Parse a task date string to datetime object.
    
    Args:
        date_str: Date string (ISO format)
        default_tz: Default timezone if date_str doesn't have timezone info
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not date_str:
        return None
    
    try:
        # Normalize timezone format
        normalized = date_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalized)
        
        # Apply default timezone if needed
        if dt.tzinfo is None and default_tz:
            dt = dt.replace(tzinfo=default_tz)
        
        return dt
    except Exception as e:
        logger.debug(f"Failed to parse datetime '{date_str}': {e}")
        return None


def is_task_overdue(due_date_str: Optional[str], status: str = 'pending') -> bool:
    """
    Check if a task is overdue.
    
    Args:
        due_date_str: Task due date string (ISO format)
        status: Task status (overdue check only applies to non-completed tasks)
        
    Returns:
        True if task is overdue, False otherwise
    """
    if not due_date_str or status == 'completed':
        return False
    
    try:
        due_dt = parse_task_datetime(due_date_str)
        if not due_dt:
            return False
        
        now = datetime.now(due_dt.tzinfo) if due_dt.tzinfo else datetime.now()
        return due_dt < now
    except Exception:
        return False


# ============================================================================
# TASK FORMATTING UTILITIES
# ============================================================================

def format_task_from_google(google_task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a Google Tasks API response into standardized task dictionary.
    
    Google Tasks API status values:
    - 'needsAction' = pending task (default for new tasks)
    - 'completed' = completed task
    
    Args:
        google_task: Task dictionary from Google Tasks API
        
    Returns:
        Formatted task dictionary with standardized fields
    """
    # Google Tasks API returns 'needsAction' for pending tasks, 'completed' for completed tasks
    google_status = google_task.get('status', 'needsAction')
    completed_timestamp = google_task.get('completed')
    deleted = google_task.get('deleted', False)
    
    # CRITICAL: Check if task is actually deleted - exclude deleted tasks
    if deleted:
        # Return None or empty dict to signal this task should be filtered out
        # But we'll handle this in the caller to avoid breaking existing code
        mapped_status = 'deleted'
    elif google_status == 'completed':
        # CRITICAL: Google Tasks API sync issue workaround
        # If status is 'completed' but there's NO completed timestamp,
        # it might be an uncompleted task (sync issue)
        # Only treat as pending if updated recently (within last 2 days) to avoid false positives
        if not completed_timestamp:
            updated_timestamp = google_task.get('updated')
            if updated_timestamp:
                try:
                    from datetime import datetime
                    import dateutil.parser
                    updated_dt = dateutil.parser.parse(updated_timestamp)
                    now = datetime.now(updated_dt.tzinfo) if updated_dt.tzinfo else datetime.utcnow()
                    days_since_update = (now - updated_dt).days
                    # If updated within last 2 days and no completed timestamp, likely uncompleted
                    if days_since_update <= 2:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.debug(f"Task '{google_task.get('title', 'NO TITLE')[:50]}' has status='completed' but no completed timestamp and updated {days_since_update} days ago - treating as pending (sync issue)")
                        mapped_status = 'pending'
                    else:
                        mapped_status = 'completed'
                except Exception:
                    mapped_status = 'completed'
            else:
                mapped_status = 'completed'
        else:
            # Has completed timestamp - trust the API
            mapped_status = 'completed'
    else:
        # 'needsAction' or any other value maps to 'pending'
        mapped_status = 'pending'
    
    return {
        'id': google_task.get('id'),
        'title': google_task.get('title', ''),
        'description': google_task.get('title', ''),  # Google Tasks uses 'title' as description
        'notes': google_task.get('notes', ''),
        'status': mapped_status,  # Formatted status ('pending' or 'completed')
        'raw_status': google_status,  # CRITICAL: Preserve raw Google API status ('needsAction' or 'completed') for filtering
        'completed': completed_timestamp,  # CRITICAL: Preserve completed timestamp to detect uncompleted tasks
        'due_date': google_task.get('due'),
        'due': google_task.get('due'),  # Keep original for compatibility
        'updated': google_task.get('updated'),
        'position': google_task.get('position'),
        'parent': google_task.get('parent'),
        'links': google_task.get('links', [])
    }


def generate_task_id(description: str, existing_count: int = 0) -> str:
    """
    Generate a unique task ID.
    
    Args:
        description: Task description
        existing_count: Number of existing tasks (for uniqueness)
        
    Returns:
        Generated task ID string
    """
    return f"task_{existing_count + 1}_{hash(description) % 10000}"

