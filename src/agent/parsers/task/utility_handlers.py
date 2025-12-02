"""
Task Utility Handlers - Common utility functions and helpers

This module contains handlers for:
- Task parsing from results
- Response formatting
- Date/time utilities  
- Validation helpers
- Common extraction utilities
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from ....utils.logger import setup_logger
from .constants import TaskParserConfig

logger = setup_logger(__name__)

# Constants for utility handlers
MIN_DESCRIPTION_LENGTH = TaskParserConfig.MIN_DESCRIPTION_LENGTH
MIN_DESCRIPTION_LENGTH_STRICT = TaskParserConfig.MIN_DESCRIPTION_LENGTH_STRICT
MAX_TASKS_DISPLAY = TaskParserConfig.MAX_TASKS_DISPLAY


class TaskUtilityHandlers:
    """Handlers for common utility functions and helpers"""
    
    def __init__(self, task_parser):
        """Initialize with reference to main TaskParser"""
        self.task_parser = task_parser
        self.logger = logger
    
    def parse_tasks_from_formatted_result(self, formatted_result: str) -> List[Dict[str, Any]]:
        """Parse tasks from formatted result string"""
        tasks = []
        
        try:
            # Handle JSON format first
            if formatted_result.strip().startswith('[') or formatted_result.strip().startswith('{'):
                try:
                    parsed = json.loads(formatted_result)
                    if isinstance(parsed, list):
                        return parsed
                    elif isinstance(parsed, dict):
                        return [parsed]
                except json.JSONDecodeError:
                    pass
            
            # Handle different result formats
            if not formatted_result or formatted_result.strip() == "":
                return []
            
            # Remove status/header lines and split into lines
            lines = formatted_result.split('\\n')
            task_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Skip status/header lines
                if line.startswith('[') and line.endswith(']'):
                    continue
                if line.startswith('Tasks:') or line.startswith('Found'):
                    continue
                if line.startswith('Total:') or line.startswith('Count:'):
                    continue
                    
                # Look for task-like patterns
                if any(indicator in line for indicator in ['•', '-', '★', '◦', '▪', '→']):
                    task_lines.append(line)
                elif re.match(r'^\\d+\\.', line):  # Numbered list
                    task_lines.append(line)
                elif re.match(r'^[A-Z]', line) and len(line) > 10:  # Likely a task description
                    task_lines.append(line)
                elif ':' in line and len(line) > 10:  # Key-value format
                    task_lines.append(line)
            
            # Parse each task line
            for line in task_lines:
                task = self.parse_single_task_line(line)
                if task:
                    tasks.append(task)
                    
        except Exception as e:
            logger.warning(f"Failed to parse tasks from result: {e}")
        
        return tasks
    
    def parse_single_task_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single task line into structured data"""
        try:
            original_line = line
            
            # Clean up the line
            line = re.sub(r'^[•\\-★◦▪→]\\s*', '', line)  # Remove bullets
            line = re.sub(r'^\\d+\\.\\s*', '', line)      # Remove numbering
            line = line.strip()
            
            if not line or len(line) < MIN_DESCRIPTION_LENGTH_STRICT:
                return None
            
            # Initialize task structure
            task = {
                "description": line,
                "status": "pending",
                "priority": "medium",
                "original_line": original_line
            }
            
            # Extract priority indicators
            priority_indicators = {
                "high": ['urgent', 'high', '!!!', 'asap', 'critical', '🔥', '⚠️'],
                "low": ['low', 'maybe', 'optional', '💤', '⏳']
            }
            
            line_lower = line.lower()
            for priority, indicators in priority_indicators.items():
                if any(indicator in line_lower for indicator in indicators):
                    task["priority"] = priority
                    break
            
            # Extract due date patterns
            due_patterns = [
                r'due[:\\s]+([\\w\\-/]+)',
                r'by[:\\s]+([\\w\\-/]+)',  
                r'deadline[:\\s]+([\\w\\-/]+)',
                r'\\(due[:\\s]*([\\w\\-/]+)\\)',
                r'\\(([\\w\\-/]+)\\)',  # Generic parentheses
            ]
            
            for pattern in due_patterns:
                match = re.search(pattern, line_lower)
                if match:
                    due_text = match.group(1).strip()
                    if self._looks_like_date(due_text):
                        task["due_date"] = due_text
                        # Remove due date from description
                        task["description"] = re.sub(pattern, '', task["description"], flags=re.IGNORECASE).strip()
                        break
            
            # Extract category/project indicators
            category_patterns = [
                r'\\[([^\\]]+)\\]',        # [category]
                r'@([\\w\\-]+)',           # @project
                r'#([\\w\\-]+)',           # #tag
                r'\\{([^\\}]+)\\}',        # {category}
            ]
            
            for pattern in category_patterns:
                match = re.search(pattern, line)
                if match:
                    category_text = match.group(1).strip()
                    if len(category_text) > 1:
                        # Determine if it's a category, project, or tag
                        if pattern.startswith(r'@'):
                            task["project"] = category_text
                        elif pattern.startswith(r'#'):
                            if "tags" not in task:
                                task["tags"] = []
                            task["tags"].append(category_text)
                        else:
                            task["category"] = category_text
                        
                        # Remove from description
                        task["description"] = re.sub(pattern, '', task["description"]).strip()
            
            # Extract status indicators
            status_patterns = {
                "completed": ['✓', '✅', '☑️', 'done', 'completed', 'finished'],
                "in_progress": ['→', '▶️', '🔄', 'in progress', 'working on'],
                "pending": ['○', '◯', '⭕', 'pending', 'todo'],
                "cancelled": ['❌', '🚫', 'cancelled', 'canceled']
            }
            
            for status, indicators in status_patterns.items():
                if any(indicator in line_lower for indicator in indicators):
                    task["status"] = status
                    break
            
            # Extract estimated time
            time_patterns = [
                r'(\\d+(?:\\.\\d+)?)\\s*h(?:ours?)?',
                r'(\\d+)\\s*m(?:in|inutes?)?',
                r'~(\\d+(?:\\.\\d+)?)\\s*h',
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, line_lower)
                if match:
                    time_val = float(match.group(1))
                    if 'm' in pattern:  # minutes
                        time_val = time_val / 60.0
                    task["estimated_hours"] = time_val
                    # Remove from description
                    task["description"] = re.sub(pattern, '', task["description"], flags=re.IGNORECASE).strip()
                    break
            
            # Clean up description
            task["description"] = ' '.join(task["description"].split())
            
            # Validate we still have a meaningful description
            if len(task["description"]) < MIN_DESCRIPTION_LENGTH:
                task["description"] = original_line
            
            return task
            
        except Exception as e:
            logger.warning(f"Failed to parse task line '{line}': {e}")
            # Return basic task structure
            return {
                "description": line,
                "status": "pending",
                "priority": "medium",
                "original_line": line
            }
    
    def _looks_like_date(self, text: str) -> bool:
        """Check if text looks like a date"""
        if not text or len(text) < 3:
            return False
        
        # Date patterns to match
        date_patterns = [
            r'\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}',  # MM/DD/YYYY, MM-DD-YY
            r'\\d{4}[/-]\\d{1,2}[/-]\\d{1,2}',     # YYYY/MM/DD
            r'\\d{1,2}[/-]\\d{1,2}',               # MM/DD
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',  # Month names
            r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)',  # Day names
            r'(today|tomorrow|yesterday)',
        ]
        
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in date_patterns)
    
    def format_task_list_for_display(self, tasks: List[Dict[str, Any]], max_tasks: int = MAX_TASKS_DISPLAY) -> str:
        """Format task list for user-friendly display"""
        if not tasks:
            return "No tasks found."
        
        formatted_lines = []
        
        for i, task in enumerate(tasks[:max_tasks]):
            desc = task.get("description", "Unknown task")
            status = task.get("status", "pending")
            priority = task.get("priority", "medium")
            due_date = task.get("due_date")
            category = task.get("category")
            
            # Build display line
            line = f"{i+1}. {desc}"
            
            # Add status indicator
            status_icons = {
                "completed": "✅",
                "in_progress": "🔄", 
                "pending": "⏳",
                "cancelled": "❌"
            }
            icon = status_icons.get(status, "⏳")
            line = f"{icon} {line}"
            
            # Add priority indicator
            if priority == "high":
                line += " [HIGH PRIORITY]"
            elif priority == "low":
                line += " [Low Priority]"
            
            # Add due date
            if due_date:
                line += f" (Due: {due_date})"
            
            # Add category
            if category:
                line += f" [{category}]"
            
            formatted_lines.append(line)
        
        result = "\\n".join(formatted_lines)
        
        # Add summary if there are more tasks
        if len(tasks) > max_tasks:
            result += f"\\n... and {len(tasks) - max_tasks} more tasks"
        
        return result
    
    def extract_keywords_from_query(self, query: str) -> List[str]:
        """Extract meaningful keywords from a query"""
        # Remove common stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after',
            'above', 'below', 'between', 'among', 'until', 'while', 'where', 'when', 'why',
            'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some',
            'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
            'can', 'will', 'just', 'should', 'now', 'i', 'you', 'he', 'she', 'it', 'we',
            'they', 'them', 'their', 'what', 'which', 'who', 'whom', 'this', 'that', 'these',
            'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has',
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'must', 'shall', 'please', 'help', 'me'
        }
        
        # Clean and split query
        query_clean = re.sub(r'[^\\w\\s]', ' ', query.lower())
        words = query_clean.split()
        
        # Filter out stop words and short words
        keywords = [word for word in words if word not in stop_words and len(word) > MIN_DESCRIPTION_LENGTH]
        
        return keywords
    
    def calculate_task_similarity(self, task1: Dict[str, Any], task2: Dict[str, Any]) -> float:
        """Calculate similarity between two tasks (0-1 score)"""
        desc1 = task1.get("description", "").lower()
        desc2 = task2.get("description", "").lower()
        
        if not desc1 or not desc2:
            return 0.0
        
        # Simple keyword-based similarity
        words1 = set(re.findall(r'\\w+', desc1))
        words2 = set(re.findall(r'\\w+', desc2))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    def group_tasks_by_category(self, tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group tasks by category"""
        grouped = {}
        
        for task in tasks:
            category = task.get("category", "Uncategorized")
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(task)
        
        return grouped
    
    def group_tasks_by_priority(self, tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group tasks by priority"""
        grouped = {"high": [], "medium": [], "low": []}
        
        for task in tasks:
            priority = task.get("priority", "medium")
            if priority in grouped:
                grouped[priority].append(task)
            else:
                grouped["medium"].append(task)
        
        return grouped
    
    def group_tasks_by_due_date(self, tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group tasks by due date categories"""
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        week_from_now = today + timedelta(days=7)
        
        grouped = {
            "overdue": [],
            "today": [],
            "tomorrow": [],
            "this_week": [],
            "later": [],
            "no_due_date": []
        }
        
        for task in tasks:
            due_date_str = task.get("due_date")
            if not due_date_str:
                grouped["no_due_date"].append(task)
                continue
            
            try:
                # Parse due date
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                
                if due_date < today:
                    grouped["overdue"].append(task)
                elif due_date == today:
                    grouped["today"].append(task)
                elif due_date == tomorrow:
                    grouped["tomorrow"].append(task)
                elif due_date <= week_from_now:
                    grouped["this_week"].append(task)
                else:
                    grouped["later"].append(task)
                    
            except (ValueError, TypeError):
                grouped["no_due_date"].append(task)
        
        return grouped
    
    def validate_task_data(self, task_data: Dict[str, Any]) -> List[str]:
        """Validate task data and return list of issues"""
        issues = []
        
        # Check required fields
        if not task_data.get("description"):
            issues.append("Task description is required")
        elif len(task_data["description"].strip()) < 2:
            issues.append("Task description is too short")
        
        # Validate priority
        from .constants import TaskPriorities
        priority = task_data.get("priority")
        if priority and priority not in TaskPriorities.all():
            issues.append(f"Invalid priority '{priority}'. Must be {', '.join(TaskPriorities.all())}")
        
        # Validate due date
        due_date = task_data.get("due_date")
        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except (ValueError, TypeError):
                issues.append(f"Invalid due date format '{due_date}'. Use YYYY-MM-DD")
        
        # Validate estimated hours
        estimated_hours = task_data.get("estimated_hours")
        if estimated_hours is not None:
            try:
                hours = float(estimated_hours)
                if hours < 0 or hours > TaskParserConfig.MAX_DESCRIPTION_LENGTH:
                    issues.append(f"Estimated hours must be between 0 and {TaskParserConfig.MAX_DESCRIPTION_LENGTH}")
            except (ValueError, TypeError):
                issues.append("Estimated hours must be a number")
        
        return issues
    
    def clean_task_description(self, description: str) -> str:
        """Clean and normalize task description"""
        if not description:
            return ""
        
        # Remove extra whitespace
        description = ' '.join(description.split())
        
        # Remove common prefixes that might have been missed
        prefixes_to_remove = [
            r'^(task\\s*:\\s*)',
            r'^(todo\\s*:\\s*)', 
            r'^(reminder\\s*:\\s*)',
            r'^(note\\s*:\\s*)'
        ]
        
        for prefix in prefixes_to_remove:
            description = re.sub(prefix, '', description, flags=re.IGNORECASE).strip()
        
        return description.strip()
    
    def generate_task_summary(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary statistics for a list of tasks"""
        if not tasks:
            return {"total": 0}
        
        summary = {
            "total": len(tasks),
            "by_status": {},
            "by_priority": {},
            "by_category": {},
            "with_due_dates": 0,
            "overdue": 0
        }
        
        today = datetime.now().date()
        
        for task in tasks:
            # Count by status
            status = task.get("status", "pending")
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
            
            # Count by priority
            priority = task.get("priority", "medium")
            summary["by_priority"][priority] = summary["by_priority"].get(priority, 0) + 1
            
            # Count by category
            category = task.get("category", "Uncategorized")
            summary["by_category"][category] = summary["by_category"].get(category, 0) + 1
            
            # Count due dates
            if task.get("due_date"):
                summary["with_due_dates"] += 1
                
                # Check if overdue
                try:
                    due_date = datetime.strptime(task["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        summary["overdue"] += 1
                except (ValueError, TypeError):
                    pass
        
        return summary
