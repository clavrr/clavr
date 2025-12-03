"""
Task Search Utilities - Enhanced search capabilities for tasks
"""
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from ...utils.logger import setup_logger
from .utils import parse_task_datetime, is_task_overdue

logger = setup_logger(__name__)


def fuzzy_match(query: str, text: str, threshold: float = 0.6) -> float:
    """
    Calculate fuzzy match score between query and text
    
    Args:
        query: Search query
        text: Text to match against
        threshold: Minimum similarity threshold
        
    Returns:
        Similarity score (0.0 to 1.0)
    """
    query_lower = query.lower()
    text_lower = text.lower()
    
    # Exact match
    if query_lower in text_lower:
        return 1.0
    
    # Word-level matching
    query_words = set(query_lower.split())
    text_words = set(text_lower.split())
    
    if not query_words:
        return 0.0
    
    # Calculate word overlap
    common_words = query_words.intersection(text_words)
    word_score = len(common_words) / len(query_words)
    
    # Calculate sequence similarity
    sequence_score = SequenceMatcher(None, query_lower, text_lower).ratio()
    
    # Combined score
    combined_score = (word_score * 0.6 + sequence_score * 0.4)
    
    return combined_score if combined_score >= threshold else 0.0


def extract_keywords(query: str) -> List[str]:
    """
    Extract important keywords from search query
    
    Args:
        query: Search query
        
    Returns:
        List of keywords
    """
    # Remove common stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be',
        'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that',
        'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her',
        'its', 'our', 'their', 'find', 'search', 'show', 'list', 'get',
        'task', 'tasks', 'todo', 'todos'
    }
    
    # Extract words
    words = re.findall(r'\b\w+\b', query.lower())
    
    # Filter out stop words and short words
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    
    return keywords


def search_tasks(
    tasks: List[Dict[str, Any]],
    query: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    project: Optional[str] = None,
    due_before: Optional[str] = None,
    due_after: Optional[str] = None,
    overdue_only: bool = False,
    fuzzy_threshold: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Enhanced multi-criteria task search
    
    Args:
        tasks: List of tasks to search
        query: Text search query (fuzzy matching)
        status: Filter by status
        priority: Filter by priority
        category: Filter by category
        tags: Filter by tags (any match)
        project: Filter by project
        due_before: Tasks due before this date (ISO format)
        due_after: Tasks due after this date (ISO format)
        overdue_only: Only return overdue tasks
        fuzzy_threshold: Minimum fuzzy match score
        
    Returns:
        Filtered and ranked list of tasks
    """
    results = []
    
    # Extract keywords if query provided
    keywords = extract_keywords(query) if query else []
    
    for task in tasks:
        score = 1.0  # Base score
        matched = True
        
        # Status filter
        if status and task.get('status') != status:
            matched = False
        
        # Priority filter
        if priority and task.get('priority') != priority.lower():
            matched = False
        
        # Category filter
        if category and task.get('category') != category:
            matched = False
        
        # Tags filter (any tag match)
        if tags:
            task_tags = task.get('tags', [])
            if not any(tag in task_tags for tag in tags):
                matched = False
        
        # Project filter
        if project and task.get('project') != project:
            matched = False
        
        # Due date filters
        task_due = task.get('due_date')
        if task_due:
            try:
                due_dt = parse_task_datetime(task_due)
                if not due_dt:
                    # If parsing fails, skip date-based filters
                    pass
                else:
                    # Overdue check
                    if overdue_only and not is_task_overdue(task_due, task.get('status', 'pending')):
                        matched = False
                    
                    # Due before filter
                    if due_before:
                        before_dt = parse_task_datetime(due_before)
                        if before_dt and due_dt > before_dt:
                            matched = False
                    
                    # Due after filter
                    if due_after:
                        after_dt = parse_task_datetime(due_after)
                        if after_dt and due_dt < after_dt:
                            matched = False
            except Exception as e:
                logger.debug(f"Error parsing due date: {e}")
        
        # Text search (fuzzy matching)
        if query and matched:
            description = task.get('description', '').lower()
            notes = task.get('notes', '').lower()
            combined_text = f"{description} {notes}".strip()
            
            # Calculate fuzzy match score
            fuzzy_score = fuzzy_match(query, combined_text, fuzzy_threshold)
            
            if fuzzy_score > 0:
                score = fuzzy_score
            else:
                # Check keyword matching
                if keywords:
                    keyword_matches = sum(1 for kw in keywords if kw in combined_text)
                    if keyword_matches > 0:
                        score = keyword_matches / len(keywords)
                    else:
                        matched = False
                else:
                    matched = False
        
        if matched:
            # Add relevance score to task
            task_with_score = task.copy()
            task_with_score['_relevance_score'] = score
            results.append(task_with_score)
    
    # Sort by relevance score (descending), then by priority, then by due date
    priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    results.sort(key=lambda t: (
        -t.get('_relevance_score', 0),  # Negative for descending
        priority_order.get(t.get('priority', 'medium'), 2),
        t.get('due_date') or '9999-12-31'
    ))
    
    return results

