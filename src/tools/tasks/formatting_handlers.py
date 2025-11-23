"""
Task Formatting Handlers

Handles formatting of task lists, analytics, and other display operations.
This module centralizes formatting logic to keep the main TaskTool class clean.
"""
from typing import List, Dict, Any, Optional

from ...utils.logger import setup_logger
from ...ai.prompts import TASK_CONVERSATIONAL_LIST, TASK_CONVERSATIONAL_EMPTY
from ...ai.prompts import get_agent_system_prompt
from ...utils.config import Config
from .constants import (
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    MAX_TASKS_FOR_LLM_CONTEXT,
    MAX_COMPLETED_TASKS_FOR_CONTEXT
)

logger = setup_logger(__name__)


def _get_safe_system_prompt() -> str:
    """
    Safely get the agent system prompt with error handling.
    
    Returns:
        System prompt string (never None)
    """
    try:
        system_prompt = get_agent_system_prompt()
        if not system_prompt or not isinstance(system_prompt, str):
            logger.warning(f"[TASK] get_agent_system_prompt() returned invalid value: {system_prompt}, using fallback")
            return "You are Clavr, an intelligent personal assistant. Provide helpful, natural, conversational responses."
        return system_prompt
    except Exception as e:
        logger.warning(f"[TASK] Failed to get agent system prompt: {e}, using fallback")
        return "You are Clavr, an intelligent personal assistant. Provide helpful, natural, conversational responses."


class TaskFormattingHandlers:
    """
    Handles task formatting operations.
    
    This class centralizes formatting logic to improve maintainability
    and keep the main TaskTool class focused on orchestration.
    """
    
    def __init__(self, task_tool):
        """
        Initialize formatting handlers.
        
        Args:
            task_tool: Parent TaskTool instance for accessing services, config, etc.
        """
        self.task_tool = task_tool
        self.config = task_tool.config if hasattr(task_tool, 'config') else None
    
    def format_task_list(
        self,
        tasks: List[Dict[str, Any]],
        title: str,
        query: str = ""
    ) -> str:
        """
        Format task list for display with conversational response.
        
        Args:
            tasks: List of task dictionaries
            title: Title for the task list
            query: Original query for conversational context
            
        Returns:
            Formatted task list string
        """
        if not tasks:
            # Even for no tasks, make it conversational
            if query:
                try:
                    from ...ai.llm_factory import LLMFactory
                    from langchain_core.messages import HumanMessage, SystemMessage
                    
                    # Use self.config if available, otherwise fall back to Config.from_env()
                    config = self.config if self.config else Config.from_env()
                    llm = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE)
                    
                    if llm:
                        # Use centralized prompt with AGENT_SYSTEM_PROMPT
                        prompt = TASK_CONVERSATIONAL_EMPTY.format(query=query)
                        
                        messages = [
                            SystemMessage(content=_get_safe_system_prompt()),
                            HumanMessage(content=prompt)
                        ]
                        response = llm.invoke(messages)
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        
                        if not isinstance(response_text, str):
                            response_text = str(response_text) if response_text else ""
                        
                        if response_text and len(response_text.strip()) > 0:
                            return response_text.strip()
                except Exception as e:
                    logger.debug(f"[TASK] Failed to generate conversational 'no tasks' response: {e}")
            
            # Check if we should show completed tasks count for context
            try:
                completed_tasks = self.task_tool.task_service.list_tasks(
                    status="completed", 
                    show_completed=True, 
                    limit=MAX_COMPLETED_TASKS_FOR_CONTEXT
                )
                completed_count = len(completed_tasks)
                if completed_count > 0:
                    return f"You don't have any pending tasks right now, but you've completed {completed_count} task{'s' if completed_count != 1 else ''}. Great job!"
            except Exception as e:
                logger.debug(f"Could not get completed count for empty list: {e}")
            return f"You don't have any tasks right now. Enjoy your free time!"
        
        # Try conversational response first
        if query:
            try:
                conversational = self._generate_conversational_task_list_response(tasks, query, title)
                if conversational:
                    return conversational
            except Exception as e:
                logger.warning(f"[TASK] Conversational response generation failed: {e}, using fallback")
        
        # Fallback to natural sentence format (NOT robotic, with bold titles)
        # Create a natural sentence instead of bullet points
        try:
            task_descriptions = []
            # Process ALL tasks, not just first 10, to ensure we don't miss any
            for task in tasks:
                task_title = task.get('title', task.get('description', 'Untitled'))
                # Only skip if title is truly empty or None, not if it's "Untitled" (might be a valid title)
                if not task_title or (isinstance(task_title, str) and task_title.strip() == ''):
                    # Try to use description if title is missing
                    task_title = task.get('description', 'Untitled')
                    if not task_title or (isinstance(task_title, str) and task_title.strip() == ''):
                        continue  # Skip tasks without any title or description
                
                due_date = task.get('due_date', task.get('due'))
                
                # Format task title in bold
                task_desc = f"**{task_title}**"
                
                # Add due date if available
                if due_date and due_date != 'No due date':
                    try:
                        from datetime import datetime
                        if isinstance(due_date, str):
                            due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        else:
                            due_dt = due_date
                        # Format date nicely
                        task_desc += f" (due {due_dt.strftime('%b %d')})"
                    except Exception:
                        pass
                
                task_descriptions.append(task_desc)
            
            # Log how many tasks we're formatting
            logger.info(f"[TASK] Formatting {len(task_descriptions)} tasks (from {len(tasks)} total tasks)")
            
            # Create natural sentence format
            if len(task_descriptions) == 0:
                # Fallback if no valid tasks found
                return f"You have {len(tasks)} task{'s' if len(tasks) != 1 else ''} in your list."
            elif len(task_descriptions) == 1:
                return f"You've got {task_descriptions[0]} on your task list."
            elif len(task_descriptions) == 2:
                return f"You've got {task_descriptions[0]} and {task_descriptions[1]} on your task list."
            else:
                # Show all tasks, not just first few
                first_few = ", ".join(task_descriptions[:-1])
                last_one = task_descriptions[-1]
                # Always show all tasks, mention total if there are more than what we're showing
                if len(tasks) > len(task_descriptions):
                    return f"You've got {first_few}, and {last_one} on your task list. That's {len(tasks)} tasks total."
                else:
                    return f"You've got {first_few}, and {last_one} on your task list."
        except Exception as e:
            logger.error(f"[TASK] Fallback formatting failed: {e}, using simple format")
            # Ultimate fallback - just return a simple message
            task_count = len(tasks)
            if task_count == 1:
                task_title = tasks[0].get('title', tasks[0].get('description', 'a task'))
                return f"You have 1 task: **{task_title}**"
            else:
                return f"You have {task_count} task{'s' if task_count != 1 else ''} in your list."
    
    def format_analytics(self, analytics: Dict[str, Any]) -> str:
        """
        Format analytics data for display.
        
        Args:
            analytics: Analytics dictionary
            
        Returns:
            Formatted analytics string
        """
        output = "**Task Analytics**\n\n"
        
        if 'total' in analytics:
            output += f"**Total Tasks:** {analytics['total']}\n"
        
        if 'by_status' in analytics:
            output += "\n**By Status:**\n"
            for status, count in analytics['by_status'].items():
                output += f"  - {status.title()}: {count}\n"
        
        if 'by_priority' in analytics:
            output += "\n**By Priority:**\n"
            for priority, count in analytics['by_priority'].items():
                output += f"  - {priority.title()}: {count}\n"
        
        if 'overdue' in analytics:
            output += f"\n**Overdue:** {analytics['overdue']} tasks\n"
        
        return output
    
    def _generate_conversational_task_list_response(
        self,
        tasks: List[Dict[str, Any]],
        query: str,
        title: str
    ) -> Optional[str]:
        """
        Generate conversational response using LLM for task lists.
        
        Args:
            tasks: List of task dictionaries
            query: Original query
            title: List title
            
        Returns:
            Conversational response string or None if generation fails
        """
        try:
            from ...ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage, SystemMessage
            from datetime import datetime
            import json
            
            # Use self.config if available, otherwise fall back to Config.from_env()
            config = self.config if self.config else Config.from_env()
            llm = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE)
            
            if not llm:
                return None
            
            # Prepare task data for LLM
            task_summaries = []
            for task in tasks[:MAX_TASKS_FOR_LLM_CONTEXT]:
                task_title = task.get('title', task.get('description', 'Untitled'))
                due_date = task.get('due_date', task.get('due', 'No due date'))
                priority = task.get('priority', 'medium')
                status = task.get('status', 'pending')
                
                task_summaries.append({
                    'title': task_title,
                    'due': due_date,
                    'priority': priority,
                    'status': status
                })
            
            # Get current time for context
            from ...core.calendar.utils import get_user_timezone
            import pytz
            
            user_tz_str = get_user_timezone()
            # Convert timezone string to timezone object
            try:
                # Use pytz to convert timezone string to timezone object
                user_tz = pytz.timezone(user_tz_str)
            except Exception:
                # Fallback to UTC if timezone conversion fails
                user_tz = pytz.UTC
            
            now = datetime.now(user_tz)
            current_time = now.strftime('%I:%M %p').lstrip('0')
            current_date = now.strftime('%A, %B %d, %Y')
            
            # Count high priority and overdue tasks
            high_priority_count = sum(1 for t in tasks if t.get('priority') == 'high')
            completed_count = sum(1 for t in tasks if t.get('status') == 'completed')
            pending_count = len(tasks) - completed_count
            
            # Use centralized prompt with get_agent_system_prompt() for consistency
            prompt = TASK_CONVERSATIONAL_LIST.format(
                query=query,
                current_time=current_time,
                current_date=current_date,
                task_count=len(tasks),
                pending_count=pending_count,
                completed_count=completed_count,
                high_priority_count=high_priority_count,
                tasks_json=json.dumps(task_summaries, indent=2)
            )
            
            # Use SystemMessage with get_agent_system_prompt() for better conversational responses
            messages = [
                SystemMessage(content=_get_safe_system_prompt()),
                HumanMessage(content=prompt)
            ]
            # Use async invoke for non-blocking LLM calls (improves streaming performance)
            import asyncio
            import concurrent.futures
            try:
                # Try async invoke first (non-blocking)
                if hasattr(llm, 'ainvoke'):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If event loop is running, execute in thread pool to avoid blocking
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(lambda: asyncio.run(llm.ainvoke(messages)))
                            response = future.result(timeout=LLM_TIMEOUT_SECONDS)
                    else:
                        response = loop.run_until_complete(llm.ainvoke(messages))
                else:
                    # Fallback to synchronous invoke in thread pool to avoid blocking
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(llm.invoke, messages)
                            response = future.result(timeout=LLM_TIMEOUT_SECONDS)
                    else:
                        response = llm.invoke(messages)
            except Exception as e:
                logger.warning(f"[TASK] Async LLM call failed, using sync fallback: {e}")
                response = llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text and len(response_text.strip()) > 0:
                # Check if response is too robotic (contains patterns we want to avoid)
                import re
                robotic_patterns = [
                    r'You have \d+ tasks?:',
                    r'^\*\*.*\*\*\s*\(\d+ tasks?\)',
                    r'^\d+\.\s',  # Numbered list at start
                    r'^\s*[\*\-]\s',  # Bullet points at start
                ]
                
                # CRITICAL: Check if task titles are in quotes instead of bold
                # Pattern to detect quoted task titles: "task title" or 'task title'
                quoted_title_patterns = [
                    r'"[^"]*"',  # Double quotes
                    r"'[^']*'",  # Single quotes
                ]
                
                # Check if response contains quoted titles (but allow quotes in other contexts)
                # We're looking for patterns like "going to the gym" or 'calling mom tonight'
                has_quoted_titles = False
                for pattern in quoted_title_patterns:
                    matches = re.findall(pattern, response_text)
                    # If we find quoted strings that look like task titles (not just punctuation)
                    for match in matches:
                        # Remove quotes to check content
                        content = match.strip('"\'')
                        # If it's a reasonable length and doesn't look like punctuation, it might be a task title
                        if len(content) > 3 and not content.startswith(('(', '[', '{')):
                            # Check if this quoted string appears near task-related words
                            context = response_text[max(0, response_text.find(match) - 50):min(len(response_text), response_text.find(match) + len(match) + 50)]
                            if any(word in context.lower() for word in ['task', 'got', 'have', 'you', 'your', 'list']):
                                has_quoted_titles = True
                                break
                    if has_quoted_titles:
                        break
                
                is_robotic = any(re.search(pattern, response_text, re.MULTILINE) for pattern in robotic_patterns)
                
                # CRITICAL: Always remove quotes from task titles, even if not detected initially
                # This ensures natural language without quotes
                cleaned_response = response_text
                
                # Remove quotes from task titles - be aggressive about this
                for pattern in quoted_title_patterns:
                    matches = re.findall(pattern, cleaned_response)
                    for match in matches:
                        content = match.strip('"\'')
                        # If it looks like a task title (reasonable length, not punctuation)
                        if len(content) > 3 and not content.startswith(('(', '[', '{')):
                            # Check context to see if it's likely a task title
                            context = cleaned_response[max(0, cleaned_response.find(match) - 50):min(len(cleaned_response), cleaned_response.find(match) + len(match) + 50)]
                            context_lower = context.lower()
                            # If near task-related words, it's likely a task title
                            if any(word in context_lower for word in ['task', 'got', 'have', 'you', 'your', 'list', 'plate', 'tackle', 'complete', 'pending']):
                                # Replace quoted title with bold (remove quotes, add bold)
                                cleaned_response = cleaned_response.replace(match, f"**{content}**", 1)
                                logger.debug(f"[TASK] Removed quotes from task title: '{match}' → **{content}**")
                
                if not is_robotic and not has_quoted_titles:
                    logger.info(f"[TASK] Generated conversational task list response")
                    return cleaned_response.strip()
                else:
                    # CRITICAL: Even if response has issues, clean it up and use it rather than failing
                    if has_quoted_titles:
                        logger.warning(f"[TASK] LLM response contained quoted task titles, cleaned up and using it")
                    else:
                        logger.warning(f"[TASK] LLM response was too robotic, cleaning up and using it")
                        # Remove robotic patterns but keep the response
                        # Remove numbered list prefixes
                        cleaned_response = re.sub(r'^\d+\.\s+', '', cleaned_response, flags=re.MULTILINE)
                        # Remove bullet points
                        cleaned_response = re.sub(r'^\s*[\*\-]\s+', '', cleaned_response, flags=re.MULTILINE)
                    return cleaned_response.strip()
            
        except Exception as e:
            logger.warning(f"[TASK] Failed to generate conversational task list response: {e}, using fallback")
            # CRITICAL: Always return a response, never None
            # Use the robust fallback formatting from format_task_list
            pass
        
        # CRITICAL: Always return a response, never None
        # Fallback to natural sentence format
        try:
            task_descriptions = []
            for task in tasks:
                task_title = task.get('title', task.get('description', 'Untitled'))
                if not task_title or (isinstance(task_title, str) and task_title.strip() == ''):
                    task_title = task.get('description', 'Untitled')
                    if not task_title or (isinstance(task_title, str) and task_title.strip() == ''):
                        continue
                
                due_date = task.get('due_date', task.get('due'))
                task_desc = f"**{task_title}**"
                
                if due_date and due_date != 'No due date':
                    try:
                        from datetime import datetime
                        if isinstance(due_date, str):
                            due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        else:
                            due_dt = due_date
                        task_desc += f" (due {due_dt.strftime('%b %d')})"
                    except Exception:
                        pass
                
                task_descriptions.append(task_desc)
            
            if len(task_descriptions) == 0:
                return f"You have {len(tasks)} task{'s' if len(tasks) != 1 else ''} in your list."
            elif len(task_descriptions) == 1:
                return f"You've got {task_descriptions[0]} on your task list."
            elif len(task_descriptions) == 2:
                return f"You've got {task_descriptions[0]} and {task_descriptions[1]} on your task list."
            else:
                first_few = ", ".join(task_descriptions[:-1])
                last_one = task_descriptions[-1]
                return f"You've got {first_few}, and {last_one} on your task list."
        except Exception as e:
            logger.error(f"[TASK] Fallback formatting failed: {e}")
            task_count = len(tasks)
            if task_count == 1:
                task_title = tasks[0].get('title', tasks[0].get('description', 'a task'))
                return f"You have 1 task: **{task_title}**"
            else:
                return f"You have {task_count} task{'s' if task_count != 1 else ''} in your list."

