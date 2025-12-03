"""
Task Analytics Handlers - Analytics and productivity insights functionality

This module contains handlers for:
- Analytics action handling
- Task analysis and insights 
- Due date analysis
- Productivity metrics
- Report generation
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import TaskParserConfig

logger = setup_logger(__name__)

# Constants for analytics handlers
DEFAULT_UPCOMING_DAYS = TaskParserConfig.DEFAULT_UPCOMING_DAYS
DEFAULT_COMPLETED_LIMIT = TaskParserConfig.DEFAULT_TASK_LIMIT
MAX_TASKS_ANALYSIS = TaskParserConfig.MAX_TASKS_ANALYSIS
MIN_TASK_LINE_LENGTH = 10


class TaskAnalyticsHandlers:
    """Handlers for task analytics and productivity insights"""
    
    def __init__(self, task_parser):
        """Initialize with reference to main TaskParser"""
        self.task_parser = task_parser
        self.logger = logger
    
    def handle_analytics_action(self, tool: BaseTool, query: str) -> str:
        """Handle analytics and insights action"""
        analysis_type = self._extract_analysis_type(query)
        
        # Different types of analytics
        if analysis_type in ["productivity", "stats", "statistics"]:
            return tool._run(action="get_productivity_stats")
        elif analysis_type in ["overdue", "late"]:
            return tool._run(action="get_overdue")
        elif analysis_type in ["upcoming", "due", "deadline"]:
            return tool._run(action="get_upcoming", days=DEFAULT_UPCOMING_DAYS)
        elif analysis_type in ["completion", "completed"]:
            return tool._run(action="get_completed", limit=DEFAULT_COMPLETED_LIMIT)
        elif analysis_type in ["categories", "category"]:
            return tool._run(action="get_by_category")
        elif analysis_type in ["priority", "priorities"]:
            return tool._run(action="get_by_priority") 
        else:
            # General analysis
            return self._parse_and_analyze_tasks(tool, query)
    
    def parse_and_analyze_tasks(self, tool: BaseTool, query: str) -> str:
        """Parse and analyze tasks based on query"""
        logger.info(f"[NOTE] Analyzing tasks for query: {query}")
        
        try:
            analysis_type = self._extract_analysis_type(query)
            
            # Get tasks based on analysis type
            if analysis_type == "overdue":
                result = tool._run(action="get_overdue")
            elif analysis_type == "due_today":
                result = tool._run(action="get_due_today") 
            elif analysis_type == "due_this_week":
                result = tool._run(action="get_upcoming", days=DEFAULT_UPCOMING_DAYS)
            elif analysis_type == "high_priority":
                result = tool._run(action="get_by_priority", priority="high")
            elif analysis_type == "category":
                # Extract category from query
                category = self._extract_category_from_query(query)
                if category:
                    result = tool._run(action="get_by_category", category=category)
                else:
                    result = tool._run(action="get_by_category")
            else:
                # Default: get all pending tasks
                result = tool._run(action="list", status="pending")
            
            # Parse tasks from result
            tasks = self._parse_tasks_from_result(result)
            
            if not tasks:
                return "[TASK] No tasks found for analysis."
            
            # Generate analysis response
            return self._generate_conversational_task_analysis_response(
                tasks=tasks,
                analysis_type=analysis_type,
                query=query
            )
            
        except Exception as e:
            logger.error(f"Task analysis failed: {e}")
            return f"[ERROR] Failed to analyze tasks: {str(e)}"
    
    def _extract_analysis_type(self, query: str) -> str:
        """Extract type of analysis from query"""
        query_lower = query.lower()
        
        # Overdue tasks
        if any(word in query_lower for word in ["overdue", "late", "past due", "missed"]):
            return "overdue"
        
        # Due date analysis  
        if any(word in query_lower for word in ["due today", "today", "due this week", "this week"]):
            if "today" in query_lower:
                return "due_today"
            elif "week" in query_lower:
                return "due_this_week"
        
        # Priority analysis
        if any(word in query_lower for word in ["high priority", "urgent", "important"]):
            return "high_priority"
        
        # Category analysis
        if any(word in query_lower for word in ["category", "project", "type"]):
            return "category"
            
        # Productivity/stats
        if any(word in query_lower for word in ["productivity", "stats", "statistics", "performance"]):
            return "productivity"
        
        # Completion analysis
        if any(word in query_lower for word in ["completed", "done", "finished"]):
            return "completion"
        
        # Default general analysis
        return "general"
    
    def _extract_category_from_query(self, query: str) -> Optional[str]:
        """Extract category from analysis query"""
        query_lower = query.lower()
        
        # Common categories
        categories = {
            "work": ["work", "job", "office", "business"],
            "personal": ["personal", "home", "family"],
            "health": ["health", "fitness", "medical", "doctor"],
            "shopping": ["shopping", "buy", "purchase", "store"],
            "finance": ["finance", "money", "budget", "bank"],
            "travel": ["travel", "trip", "vacation", "flight"],
            "education": ["education", "learn", "study", "course"]
        }
        
        for category, keywords in categories.items():
            if any(keyword in query_lower for keyword in keywords):
                return category
        
        # Try to extract explicit category mentions
        category_match = re.search(r'category[:\s]+([a-zA-Z]+)', query_lower)
        if category_match:
            return category_match.group(1)
            
        project_match = re.search(r'project[:\s]+([a-zA-Z]+)', query_lower)
        if project_match:
            return project_match.group(1)
        
        return None
    
    def _parse_tasks_from_result(self, result: str) -> List[Dict[str, Any]]:
        """Parse tasks from tool result string"""
        tasks = []
        
        try:
            # Handle different result formats
            if not result or result.strip() == "":
                return []
            
            # If result starts with [ERROR], [TASK], etc., extract main content
            lines = result.split('\n')
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
                    
                # Look for task-like patterns
                if any(indicator in line for indicator in ['•', '-', '★', '◦', '▪']):
                    task_lines.append(line)
                elif re.match(r'^\d+\.', line):  # Numbered list
                    task_lines.append(line)
                elif len(line) > MIN_TASK_LINE_LENGTH:  # Likely a task description
                    task_lines.append(line)
            
            # Parse each task line
            for line in task_lines:
                task = self._parse_single_task_line(line)
                if task:
                    tasks.append(task)
        
        except Exception as e:
            logger.warning(f"Failed to parse tasks from result: {e}")
        
        return tasks
    
    def _parse_single_task_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single task line into structured data"""
        try:
            # Clean up the line
            line = re.sub(r'^[•\-★◦▪]\s*', '', line)  # Remove bullets
            line = re.sub(r'^\d+\.\s*', '', line)     # Remove numbering
            line = line.strip()
            
            if not line:
                return None
            
            # Extract basic task info
            task = {
                "description": line,
                "status": "pending",
                "priority": "medium"
            }
            
            # Look for priority indicators
            if any(indicator in line.lower() for indicator in ['urgent', 'high', '!!!', 'asap']):
                task["priority"] = "high"
            elif any(indicator in line.lower() for indicator in ['low', 'maybe', 'optional']):
                task["priority"] = "low"
            
            # Look for due date patterns
            due_patterns = [
                r'due\s+(\w+)',
                r'by\s+(\w+)',
                r'deadline\s+(\w+)',
                r'(\w+day)',  # today, monday, etc.
            ]
            
            for pattern in due_patterns:
                match = re.search(pattern, line.lower())
                if match:
                    task["due_date"] = match.group(1)
                    break
            
            # Look for category/project
            category_match = re.search(r'\[([^\]]+)\]', line)
            if category_match:
                task["category"] = category_match.group(1)
            
            return task
            
        except Exception as e:
            logger.warning(f"Failed to parse task line '{line}': {e}")
            return None
    
    def _generate_conversational_task_analysis_response(
        self,
        tasks: List[Dict[str, Any]], 
        analysis_type: str,
        query: str
    ) -> str:
        """Generate conversational analysis response"""
        
        if not tasks:
            return self._get_no_tasks_message(analysis_type)
        
        # Generate summary stats
        total_tasks = len(tasks)
        high_priority = len([t for t in tasks if t.get("priority") == "high"])
        has_due_dates = len([t for t in tasks if t.get("due_date")])
        
        # Generate response based on analysis type
        if analysis_type == "overdue":
            return self._generate_overdue_analysis(tasks, total_tasks)
        elif analysis_type in ["due_today", "due_this_week"]:
            return self._generate_due_date_analysis(tasks, analysis_type, total_tasks)
        elif analysis_type == "high_priority":
            return self._generate_priority_analysis(tasks, total_tasks)
        elif analysis_type == "category":
            return self._generate_category_analysis(tasks, total_tasks)
        elif analysis_type == "productivity":
            return self._generate_productivity_analysis(tasks, total_tasks)
        else:
            # General analysis
            return self._generate_general_analysis(tasks, total_tasks, high_priority, has_due_dates)
    
    def _generate_overdue_analysis(self, tasks: List[Dict[str, Any]], total: int) -> str:
        """Generate overdue tasks analysis"""
        if total == 0:
            return "Great news! You don't have any overdue tasks. You're staying on top of things!"
        
        task_list = self._format_task_list(tasks[:MAX_TASKS_ANALYSIS])  # Show first MAX_TASKS_ANALYSIS
        
        if total == 1:
            return f"You have 1 overdue task that needs attention:\n{task_list}"
        else:
            extra = f" (showing first {MAX_TASKS_ANALYSIS})" if total > MAX_TASKS_ANALYSIS else ""
            return f"You have {total} overdue tasks that need attention{extra}:\n{task_list}"
    
    def _generate_due_date_analysis(self, tasks: List[Dict[str, Any]], analysis_type: str, total: int) -> str:
        """Generate due date analysis"""
        period = "today" if analysis_type == "due_today" else "this week"
        
        if total == 0:
            return f"You don't have any tasks due {period}. Nice work staying ahead!"
        
        task_list = self._format_task_list(tasks[:MAX_TASKS_ANALYSIS])
        
        if total == 1:
            return f"You have 1 task due {period}:\n{task_list}"
        else:
            extra = f" (showing first {MAX_TASKS_ANALYSIS})" if total > MAX_TASKS_ANALYSIS else ""
            return f"You have {total} tasks due {period}{extra}:\n{task_list}"
    
    def _generate_priority_analysis(self, tasks: List[Dict[str, Any]], total: int) -> str:
        """Generate priority analysis"""
        if total == 0:
            return "You don't have any high priority tasks right now."
        
        task_list = self._format_task_list(tasks[:MAX_TASKS_ANALYSIS])
        
        if total == 1:
            return f"You have 1 high priority task:\n{task_list}"
        else:
            extra = f" (showing first {MAX_TASKS_ANALYSIS})" if total > MAX_TASKS_ANALYSIS else ""
            return f"You have {total} high priority tasks{extra}:\n{task_list}"
    
    def _generate_category_analysis(self, tasks: List[Dict[str, Any]], total: int) -> str:
        """Generate category analysis"""
        # Group by category
        categories = {}
        for task in tasks:
            cat = task.get("category", "Uncategorized")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(task)
        
        if not categories:
            return "I couldn't find any categorized tasks."
        
        response = f"Here's your task breakdown by category ({total} total tasks):\n\n"
        for category, cat_tasks in categories.items():
            count = len(cat_tasks)
            response += f"**{category}**: {count} task{'s' if count != 1 else ''}\n"
            if count <= 3:
                for task in cat_tasks:
                    response += f"  • {task.get('description', 'Unknown task')}\n"
            else:
                for task in cat_tasks[:2]:
                    response += f"  • {task.get('description', 'Unknown task')}\n"
                response += f"  • ...and {count - 2} more\n"
            response += "\n"
        
        return response.strip()
    
    def _generate_productivity_analysis(self, tasks: List[Dict[str, Any]], total: int) -> str:
        """Generate productivity analysis"""
        # Simple productivity metrics
        high_priority = len([t for t in tasks if t.get("priority") == "high"])
        has_due_dates = len([t for t in tasks if t.get("due_date")])
        
        response = f"**Your Productivity Overview:**\n\n"
        response += f"• Total active tasks: {total}\n"
        response += f"• High priority tasks: {high_priority}\n"
        response += f"• Tasks with due dates: {has_due_dates}\n"
        response += f"• Organization level: {self._calculate_organization_score(tasks)}%\n"
        
        # Add insights
        if high_priority > total * 0.5:
            response += "\n💡 You have a lot of high priority tasks. Consider breaking some down into smaller steps."
        elif high_priority == 0:
            response += "\n💡 Consider setting priorities to help focus your efforts."
        
        if has_due_dates < total * 0.3:
            response += "\n💡 Adding due dates could help you stay organized and meet deadlines."
        
        return response
    
    def _generate_general_analysis(self, tasks: List[Dict[str, Any]], total: int, high_priority: int, has_due_dates: int) -> str:
        """Generate general task analysis"""
        response = f"**Task Analysis Summary:**\n\n"
        response += f"You have {total} task{'s' if total != 1 else ''} in your list.\n\n"
        
        if high_priority > 0:
            response += f"• {high_priority} high priority task{'s' if high_priority != 1 else ''}\n"
        
        if has_due_dates > 0:
            response += f"• {has_due_dates} task{'s' if has_due_dates != 1 else ''} with due dates\n"
        
        # Show some tasks
        if total <= MAX_TASKS_ANALYSIS:
            response += f"\n**Your tasks:**\n{self._format_task_list(tasks)}"
        else:
            response += f"\n**Your next {MAX_TASKS_ANALYSIS} tasks:**\n{self._format_task_list(tasks[:MAX_TASKS_ANALYSIS])}"
            response += f"\n...and {total - MAX_TASKS_ANALYSIS} more tasks"
        
        return response
    
    def _get_no_tasks_message(self, analysis_type: str) -> str:
        """Get appropriate message when no tasks found"""
        messages = {
            "overdue": "Great! You don't have any overdue tasks.",
            "due_today": "You don't have any tasks due today.",
            "due_this_week": "You don't have any tasks due this week.",
            "high_priority": "You don't have any high priority tasks right now.",
            "category": "No tasks found in that category.",
            "productivity": "No tasks found to analyze.",
            "completion": "No completed tasks found.",
            "general": "You don't have any tasks in your list."
        }
        return messages.get(analysis_type, "No tasks found for this analysis.")
    
    def _format_task_list(self, tasks: List[Dict[str, Any]]) -> str:
        """Format task list for display"""
        if not tasks:
            return ""
        
        formatted = []
        for task in tasks:
            desc = task.get("description", "Unknown task")
            priority = task.get("priority", "")
            due = task.get("due_date", "")
            
            line = f"• {desc}"
            
            if priority == "high":
                line += " [HIGH PRIORITY]"
            elif priority == "low":
                line += " [Low Priority]"
            
            if due:
                line += f" (Due: {due})"
            
            formatted.append(line)
        
        return "\n".join(formatted)
    
    def _calculate_organization_score(self, tasks: List[Dict[str, Any]]) -> int:
        """Calculate a simple organization score"""
        if not tasks:
            return 100
        
        from .constants import TaskParserConfig
        score = 0
        total_points = len(tasks) * TaskParserConfig.POINTS_PER_TASK
        
        for task in tasks:
            # 1 point for having priority
            if task.get("priority") and task["priority"] != "medium":
                score += 1
            
            # 1 point for having due date
            if task.get("due_date"):
                score += 1
            
            # 1 point for having category
            if task.get("category"):
                score += 1
        
        return min(TaskParserConfig.MAX_ORGANIZATION_SCORE, int((score / total_points) * TaskParserConfig.MAX_ORGANIZATION_SCORE)) if total_points > 0 else 0
    
    def generate_conversational_due_date_tasks_response(
        self,
        formatted_result: str,
        query: str
    ) -> str:
        """Generate conversational response for due date tasks with LLM enhancement"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_due_date_response(formatted_result, query)
        
        # Parse tasks from formatted result
        tasks = self._parse_tasks_from_formatted_result(formatted_result)
        
        # Determine time context from query
        query_lower = query.lower()
        time_context = "soon"
        if "today" in query_lower:
            time_context = "today"
        elif "tomorrow" in query_lower:
            time_context = "tomorrow"
        elif "week" in query_lower:
            time_context = "this week"
        elif "month" in query_lower:
            time_context = "this month"
        
        from ....ai.prompts import TASK_ANALYTICS_RESPONSE
        
        prompt = TASK_ANALYTICS_RESPONSE.format(
            time_context=time_context,
            formatted_result=formatted_result
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_due_date_response(formatted_result, query)
    
    def _format_fallback_due_date_response(self, formatted_result: str, query: str) -> str:
        """Format fallback response for due date queries"""
        query_lower = query.lower()
        
        # Determine time context
        if "today" in query_lower:
            time_context = "today"
        elif "tomorrow" in query_lower:
            time_context = "tomorrow"
        elif "week" in query_lower:
            time_context = "this week"
        elif "month" in query_lower:
            time_context = "this month"
        else:
            time_context = "soon"
        
        # Remove technical tags
        import re
        result = re.sub(r'\[OK\]\s*', '', formatted_result, flags=re.IGNORECASE)
        result = re.sub(r'\[TASK\]\s*', '', result, flags=re.IGNORECASE)
        
        # Check if no tasks
        if "no tasks" in result.lower() or result.strip() == "":
            return f"Good news! You don't have any tasks due {time_context}."
        
        return f"Here are your tasks due {time_context}: {result}"
    
    def _parse_tasks_from_formatted_result(self, formatted_result: str) -> List[Dict[str, Any]]:
        """Parse tasks from formatted result string"""
        # This is a simplified version - could be enhanced
        tasks = []
        lines = formatted_result.split('\n')
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('[') and len(line) > 5:
                # Simple task parsing
                task = {
                    "description": line,
                    "status": "pending"
                }
                tasks.append(task)
        
        return tasks
    
    def _invoke_llm_for_response(self, prompt: str) -> Optional[str]:
        """Invoke LLM for response generation (delegated to parent)"""
        return self.task_parser._invoke_llm_for_response(prompt)
