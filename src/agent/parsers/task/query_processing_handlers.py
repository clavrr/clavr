"""
Task Query Processing Handlers - Query processing, execution and response generation

This module contains handlers for:
- Main query processing and execution
- LLM-enhanced classification
- Response generation with conversational formatting
- Validation and error handling
- Query routing and confidence management
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class TaskQueryProcessingHandlers:
    """Handlers for query processing, execution and response generation"""
    
    def __init__(self, task_parser):
        """Initialize with reference to main TaskParser"""
        self.task_parser = task_parser
        self.logger = logger
    
    def extract_actual_query(self, query: str) -> str:
        """
        Extract the actual user query from conversation context
        
        Args:
            query: Full query with conversation context
            
        Returns:
            Just the actual user query
        """
        # Look for "Current query:" pattern
        if "Current query:" in query:
            parts = query.split("Current query:")
            if len(parts) > 1:
                actual_query = parts[1].split("[Context:")[0].strip()
                return actual_query
        
        # Look for "User:" pattern (for conversation context)
        if "User:" in query:
            # Find the last "User:" occurrence
            user_parts = query.split("User:")
            if len(user_parts) > 1:
                # Get the last user message
                last_user_part = user_parts[-1]
                # Extract just the user message content
                if "Assistant:" in last_user_part:
                    actual_query = last_user_part.split("Assistant:")[0].strip()
                else:
                    actual_query = last_user_part.strip()
                return actual_query
        
        # If no conversation context, return as-is
        return query
    
    def execute_task_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any], action: str) -> str:
        """Execute task using LLM classification results"""
        logger.info(f"[NOTE] Executing task with classification - Action: {action}")
        
        # Route to appropriate handler based on action
        if action == "create":
            return self.task_parser.creation_handlers.parse_and_create_task_with_classification(tool, query, classification)
        elif action == "analyze":
            return self.task_parser.analytics_handlers.parse_and_analyze_tasks(tool, query)
        elif action == "list":
            result = tool._run(action="list")
            return self._generate_list_response(result, query)
        elif action == "complete":
            task_desc = self._extract_task_from_classification(classification, query)
            result = tool._run(action="complete", task_description=task_desc)
            return self._generate_complete_response(result, query, task_desc)
        elif action == "delete":
            task_desc = self._extract_task_from_classification(classification, query)
            result = tool._run(action="delete", task_description=task_desc)
            return self._generate_delete_response(result, query, task_desc)
        elif action == "search":
            search_terms = self._extract_search_from_classification(classification, query)
            result = tool._run(action="search", search_terms=search_terms)
            return self._generate_search_response(result, query)
        else:
            # Fallback to action handlers
            action_method_map = {
                "analytics": self.task_parser.analytics_handlers.handle_analytics_action,
                "template": self.task_parser.management_handlers.handle_template_action,
                "recurring": self.task_parser.management_handlers.handle_recurring_action,
                "reminders": self.task_parser.management_handlers.handle_reminders_action,
                "overdue": self.task_parser.management_handlers.handle_overdue_action,
                "subtasks": self.task_parser.management_handlers.handle_subtasks_action,
                "bulk": self.task_parser.management_handlers.handle_bulk_action,
            }
            
            handler = action_method_map.get(action)
            if handler:
                return handler(tool, query)
            else:
                return f"[ERROR] Unknown action: {action}"
    
    def _extract_task_from_classification(self, classification: Dict[str, Any], query: str) -> str:
        """Extract task description from classification results"""
        entities = classification.get("entities", {})
        
        # Try different entity fields
        task_desc = (entities.get("task_description") or 
                    entities.get("target_task") or 
                    entities.get("task") or
                    entities.get("description"))
        
        # Fallback to query parsing
        if not task_desc:
            task_desc = self.task_parser.management_handlers._extract_task_description_for_action(
                query, ["complete", "delete", "mark", "remove"]
            )
        
        return task_desc or ""
    
    def _extract_search_from_classification(self, classification: Dict[str, Any], query: str) -> str:
        """Extract search terms from classification results"""
        entities = classification.get("entities", {})
        
        # Try different entity fields
        search_terms = (entities.get("search_terms") or
                       entities.get("keywords") or
                       entities.get("query") or
                       entities.get("terms"))
        
        # Fallback to query parsing
        if not search_terms:
            search_terms = self.task_parser.management_handlers._extract_search_terms(query)
        
        return search_terms or ""
    
    def generate_conversational_task_response(
        self,
        formatted_result: str,
        query: str,
        action: str = "create"
    ) -> str:
        """Generate contextual, conversational response using LLM enhancement"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_response(formatted_result, action)
        
        try:
            from langchain_core.messages import HumanMessage
            from datetime import datetime
            import pytz
            
            # Get user_first_name from parser for personalization
            user_first_name = getattr(self.task_parser, 'user_first_name', None)
            
            # Gather context
            now = datetime.now(pytz.UTC)
            current_hour = now.hour
            is_late_night = current_hour >= 22
            is_early_morning = current_hour < 7
            
            # Count tasks from result
            task_count = formatted_result.count('**') if formatted_result else 0
            if task_count == 0:
                task_count = formatted_result.count('-') if formatted_result else 0
            
            # Extract task types/categories
            task_types = []
            if formatted_result:
                result_lower = formatted_result.lower()
                if any(kw in result_lower for kw in ['reading', 'read', 'book']):
                    task_types.append('reading')
                if any(kw in result_lower for kw in ['workout', 'exercise', 'gym']):
                    task_types.append('fitness')
                if any(kw in result_lower for kw in ['study', 'learn', 'course']):
                    task_types.append('learning')
            
            # Determine response type
            if action == "create":
                context_desc = "The user created a new task."
            elif action == "list":
                context_desc = f"The user has {task_count} task(s)."
            elif action == "complete":
                context_desc = "The user completed a task."
            else:
                context_desc = f"The user performed a {action} operation."
            
            # Add personalization note if user_first_name is available
            personalization_note = ""
            if user_first_name:
                personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name naturally - once or twice in the response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or 'Hey there, {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
            
            prompt = f"""You are Clavr, a friendly and encouraging personal assistant. Generate a natural, conversational response about tasks.

User asked: "{query}"
Action: {action}
Context: {context_desc}
Task count: {task_count}
Task types: {', '.join(task_types) if task_types else 'general'}
Current hour: {current_hour}:00
Is late night: {is_late_night}
Is early morning: {is_early_morning}

Tasks summary:
{formatted_result[:800] if formatted_result else 'No tasks'}

Generate a friendly response that:
1. Answers the query directly
2. Provides contextual, encouraging advice based on:
   - Task types (e.g., reading tasks → encourage reading habits)
   - Task count (many tasks → suggest prioritization/balance)
   - Time of day (late night → suggest rest, early morning → encourage)
   - Action type (completed task → celebrate, created task → encourage)
3. Be natural and warm, not robotic
4. Keep it concise (2-3 sentences max)
5. Only provide advice if genuinely helpful and relevant
{personalization_note}

Examples:
- Completed reading task → "Great job completing that reading task! Keep up the good reading habit."
- Many tasks + late night → "You have {task_count} tasks. That's a lot! Make sure to get enough rest tonight."
- Created fitness task → "Nice! Adding fitness to your tasks. You've got this!"

Response:"""

            response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content.strip()
        except Exception as e:
            logger.debug(f"[TASK] Failed to generate contextual response: {e}")
        
        # Fallback to original prompt-based approach
        from ....ai.prompts import TASK_SEARCH_RESPONSE
        prompt = TASK_SEARCH_RESPONSE.format(
            query=query,
            formatted_result=formatted_result
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_response(formatted_result, action)
    
    def _generate_complete_response(
        self,
        formatted_result: str,
        query: str,
        task_description: Optional[str] = None
    ) -> str:
        """Generate conversational response for task completion"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_response(formatted_result, "complete", task_description)
        
        from ....ai.prompts import TASK_COMPLETE_RESPONSE
        
        # Get user_first_name from parser for personalization
        user_first_name = getattr(self.task_parser, 'user_first_name', None)
        personalization_note = ""
        if user_first_name:
            personalization_note = f"The user's name is {user_first_name}. Use their name naturally - once or twice in the response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or 'Hey there, {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
        else:
            personalization_note = "No user name available - use generic friendly language."
        
        # Add personalization note to prompt if the prompt supports it
        prompt = TASK_COMPLETE_RESPONSE.format(
            query=query,
            formatted_result=formatted_result,
            personalization_note=personalization_note
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_response(formatted_result, "complete", task_description)
    
    def _generate_delete_response(
        self,
        formatted_result: str,
        query: str,
        task_description: Optional[str] = None
    ) -> str:
        """Generate conversational response for task deletion"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_response(formatted_result, "delete", task_description)
        
        from ....ai.prompts import TASK_DELETE_RESPONSE
        
        # Get user_first_name from parser for personalization
        user_first_name = getattr(self.task_parser, 'user_first_name', None)
        personalization_note = ""
        if user_first_name:
            personalization_note = f"The user's name is {user_first_name}. Use their name naturally - once or twice in the response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or 'Hey there, {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
        else:
            personalization_note = "No user name available - use generic friendly language."
        
        # Add personalization note to prompt if the prompt supports it
        prompt = TASK_DELETE_RESPONSE.format(
            query=query,
            formatted_result=formatted_result,
            personalization_note=personalization_note
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_response(formatted_result, "delete", task_description)
    
    def _generate_list_response(
        self,
        formatted_result: str,
        query: str
    ) -> str:
        """Generate conversational response for task listing"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_response(formatted_result, "list")
        
        from ....ai.prompts import TASK_LIST_RESPONSE
        
        # Get user_first_name from parser for personalization
        user_first_name = getattr(self.task_parser, 'user_first_name', None)
        personalization_note = ""
        if user_first_name:
            personalization_note = f"The user's name is {user_first_name}. Use their name naturally - once or twice in the response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or 'Hey there, {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
        else:
            personalization_note = "No user name available - use generic friendly language."
        
        prompt = TASK_LIST_RESPONSE.format(
            query=query,
            formatted_result=formatted_result,
            personalization_note=personalization_note
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_response(formatted_result, "list")
    
    def _generate_search_response(
        self,
        formatted_result: str,
        query: str
    ) -> str:
        """Generate conversational response for task search"""
        
        if not self.task_parser.llm_client:
            return self._format_fallback_response(formatted_result, "search")
        
        from ....ai.prompts import TASK_SEARCH_RESPONSE
        
        # Get user_first_name from parser for personalization
        user_first_name = getattr(self.task_parser, 'user_first_name', None)
        personalization_note = ""
        if user_first_name:
            personalization_note = f"The user's name is {user_first_name}. Use their name naturally - once or twice in the response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or 'Hey there, {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
        else:
            personalization_note = "No user name available - use generic friendly language."
        
        prompt = TASK_SEARCH_RESPONSE.format(
            query=query,
            formatted_result=formatted_result,
            personalization_note=personalization_note
        )
        
        response = self._invoke_llm_for_response(prompt)
        return response if response else self._format_fallback_response(formatted_result, "search")
    
    def _invoke_llm_for_response(self, prompt: str) -> Optional[str]:
        """Invoke LLM and extract response text"""
        try:
            from langchain_core.messages import HumanMessage
            response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
            
            # Extract response text
            if hasattr(response, 'content'):
                response_text = response.content
            elif isinstance(response, str):
                response_text = response
            else:
                response_text = str(response)
            
            # Clean up response
            response_text = response_text.strip()
            if response_text.startswith('"') and response_text.endswith('"'):
                response_text = response_text[1:-1]
            if response_text.startswith("'") and response_text.endswith("'"):
                response_text = response_text[1:-1]
            
            # Remove any technical tags
            response_text = re.sub(r'\\[OK\\]\\s*', '', response_text, flags=re.IGNORECASE)
            response_text = re.sub(r'\\[ERROR\\]\\s*', '', response_text, flags=re.IGNORECASE)
            
            return response_text
            
        except Exception as e:
            logger.warning(f"LLM invocation failed: {e}")
            return None
    
    def _format_fallback_response(
        self,
        formatted_result: str,
        action_type: str,
        task_description: Optional[str] = None
    ) -> str:
        """Format fallback response when LLM is unavailable"""
        # Remove technical tags
        result = re.sub(r'\\[OK\\]\\s*', '', formatted_result, flags=re.IGNORECASE)
        result = re.sub(r'\\[ERROR\\]\\s*', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\\[PENDING\\]\\s*', '', result, flags=re.IGNORECASE)
        
        # Make it more conversational
        if action_type == "complete":
            if "completed" in result.lower() or "done" in result.lower():
                return f"Done! I've marked '{task_description or 'that task'}' as complete."
            else:
                return f"I couldn't find a task matching '{task_description or 'that'}'."
        elif action_type == "delete":
            if "deleted" in result.lower():
                return f"Got it! I've deleted '{task_description or 'that task'}'."
            else:
                return f"I couldn't find a task matching '{task_description or 'that'}'."
        elif action_type == "list":
            if "no tasks" in result.lower() or "no task" in result.lower():
                return "You don't have any tasks in your list right now. Would you like me to help you create some?"
            else:
                return result
        elif action_type == "search":
            if "no tasks" in result.lower() or "no matching" in result.lower():
                return f"I couldn't find any tasks matching your search. Try different keywords?"
            else:
                return result
        else:
            return result
