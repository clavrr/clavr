# filepath: src/agent/parsers/email/multi_step_handlers.py
"""
Email Multi-Step Handlers - Handles complex multi-step email queries

This module provides functionality for:
- Multi-step query detection (semantic + pattern-based)
- Query decomposition into sequential steps
- Step-by-step execution with result aggregation
- Confirmation message generation
- Autonomous execution with informational confirmation

Extracted from EmailParser to improve maintainability and reduce file size.
"""
import re
import json
from typing import Dict, Any, Optional, List
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from ....ai.prompts import (
    MULTI_STEP_DETECTION_PROMPT,
    QUERY_DECOMPOSITION_PROMPT
)
from ....ai.prompts.utils import format_prompt
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for multi-step handlers
DEFAULT_STEP_LIMIT = EmailParserConfig.DEFAULT_EMAIL_LIMIT


class EmailMultiStepHandlers:
    """
    Handlers for multi-step email queries
    
    This class provides methods for detecting, decomposing, and executing
    multi-step email queries that require multiple sequential actions.
    """
    
    def __init__(self, parser):
        """
        Initialize multi-step handlers
        
        Args:
            parser: Parent EmailParser instance for accessing shared resources
        """
        self.parser = parser
        self.llm_client = parser.llm_client
    
    def is_multi_step_query(self, query: str) -> bool:
        """
        Check if query requires multiple steps using semantic analysis, not just keywords
        
        This method uses semantic understanding to determine if a query requires multiple
        distinct actions vs. asking multiple questions about the same thing.
        
        Args:
            query: User query string
            
        Returns:
            True if query requires multiple steps, False otherwise
        """
        query_lower = query.lower()
        
        # Use LLM to determine if this is truly multi-step if available
        # This provides semantic understanding rather than keyword matching
        if self.llm_client:
            try:
                semantic_check_prompt = format_prompt(
                    MULTI_STEP_DETECTION_PROMPT,
                    query=query
                )
                
                response = self.llm_client.invoke(semantic_check_prompt)
                content = response.content.strip()
                
                # Extract JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group(0))
                    is_multi = result.get('is_multi_step', False)
                    reasoning = result.get('reasoning', '')
                    logger.info(f"[EMAIL] Semantic multi-step check: is_multi_step={is_multi}, reasoning={reasoning}")
                    return is_multi
            except Exception as e:
                logger.warning(f"[EMAIL] Semantic multi-step check failed: {e}, falling back to pattern matching")
        
        # Fallback to pattern-based detection (less ideal but necessary if LLM unavailable)
        # CRITICAL: Queries that ask "what is the email about" after searching are NOT multi-step
        # They're single-step queries that need summary generation
        # Examples: "Do I have any email from X? What is the email about?" = single-step
        is_email_search_query = (
            ('email' in query_lower or 'emails' in query_lower) and
            ('from' in query_lower or 'have' in query_lower or 'got' in query_lower) and
            ('what' in query_lower and ('about' in query_lower or 'email' in query_lower))
        )
        if is_email_search_query:
            logger.info(f"[EMAIL] Detected email search + 'what about' query - treating as single-step (not multi-step)")
            return False
        
        # Simple queries like "What new emails do I have today?" should NOT be multi-step
        # These are single questions, not multiple actions
        simple_question_patterns = [
            'what', 'when', 'who', 'where', 'why', 'how', 'which',
            'show me', 'list', 'find', 'search', 'get'
        ]
        
        # If it's a simple question without action verbs, it's not multi-step
        is_simple_question = any(pattern in query_lower for pattern in simple_question_patterns)
        has_action_verbs = any(verb in query_lower for verb in ['create', 'send', 'delete', 'update', 'schedule', 'compose'])
        
        # Simple questions without multiple actions are single-step
        if is_simple_question and not has_action_verbs:
            # Check if it contains multiple distinct actions
            action_count = sum(1 for verb in ['create', 'send', 'delete', 'update', 'schedule', 'compose', 'summarize'] if verb in query_lower)
            if action_count <= 1:
                logger.info(f"[EMAIL] Detected simple question query - treating as single-step")
                return False
        
        # Special case: Email-related queries asking multiple questions about the same email
        # e.g., "When did Monique responded and what was the email about?" = single-step
        is_email_query = any(keyword in query_lower for keyword in ['email', 'emails', 'message', 'messages'])
        is_question_query = any(word in query_lower for word in ['when', 'what', 'who', 'where', 'why', 'how', 'which'])
        
        # If it's an email question query with "and", treat as single-step
        # Both parts are asking about the same email (when + what)
        if is_email_query and is_question_query and 'and' in query_lower:
            logger.info(f"[EMAIL] Detected email question query with 'and' - treating as single-step")
            return False
        
        # Check for explicit multi-step patterns (excluding "and" for question queries)
        multi_step_indicators = [' then ', ' after ', ' followed by ', ' next ', ' also ', ' plus ']
        has_multi_step_pattern = any(indicator in query_lower for indicator in multi_step_indicators)
        
        # "and" is only multi-step if it's not a question query about the same email
        if 'and' in query_lower and not (is_email_query and is_question_query):
            # Check if "and" connects different actions (not just questions)
            # If both parts are questions about the same email, it's single-step
            return True
        
        return has_multi_step_pattern
    
    def handle_multi_step_query(self, query: str, tool: BaseTool, user_id: Optional[int], session_id: Optional[str]) -> str:
        """
        Handle multi-step queries by decomposing them into sequential steps
        
        Args:
            query: User query string
            tool: Email tool to execute with
            user_id: Optional user ID
            session_id: Optional session ID
            
        Returns:
            Combined results from all steps
        """
        if not self.llm_client:
            # Fallback: If LLM is not available, try to handle as single-step query
            logger.warning("[EMAIL] Multi-step query detected but LLM not available. Falling back to single-step handling.")
            return self._execute_single_step(query, tool, user_id, session_id)
        
        try:
            # Decompose query into steps
            steps = self._decompose_query_steps(query)
            
            if not steps or len(steps) == 1:
                # Not actually multi-step, fall through to single step
                return self._execute_single_step(query, tool, user_id, session_id)
            
            # Execute steps sequentially
            results = []
            for i, step in enumerate(steps, 1):
                logger.info(f"Executing step {i}/{len(steps)}: {step.get('description', 'N/A')}")
                result = self._execute_query_step(step, tool, user_id, session_id)
                results.append(result)
            
            # Combine results
            combined = f"**Multi-step Query Results:**\n\n"
            for i, (step, result) in enumerate(zip(steps, results), 1):
                combined += f"**Step {i}: {step.get('description', 'N/A')}**\n{result}\n\n"
            
            return combined
            
        except Exception as e:
            logger.error(f"Multi-step query failed: {e}")
            return f"[ERROR] Failed to handle multi-step query: {str(e)}"
    
    def _decompose_query_steps(self, query: str) -> List[Dict[str, Any]]:
        """
        Decompose query into sequential steps using LLM
        
        Args:
            query: User query string
            
        Returns:
            List of step dictionaries with description, operation, and params
        """
        if not self.llm_client:
            return []
        
        # Build operations context for decomposition
        operations_context = """Available operations:
- search_emails(criteria) - Search emails by criteria
- list_emails(filter) - List emails with filter
- summarize_content(text) - Summarize email content
- extract_key_points(text) - Extract key points
- analyze_sentiment(text) - Analyze sentiment
- send_email(to, subject, body) - Send email
- reply_to_email(id, body) - Reply to email

Return ONLY a JSON array of steps. Each step should have:
- description: What this step does
- operation: Which operation to use
- params: Parameters for the operation

Example: [{{"description": "Search for emails from john", "operation": "search_emails", "params": {{"sender": "john@example.com", "limit": 20}}}}]

Return ONLY the JSON array, no explanations."""
        
        prompt = format_prompt(
            QUERY_DECOMPOSITION_PROMPT,
            query=query,
            operations_context=operations_context
        )
        
        try:
            # Try structured outputs first
            steps = self._decompose_email_steps_with_structured_outputs(prompt)
            if steps:
                return steps
            
            # Fallback to prompt-based parsing
            response = self.llm_client.invoke(prompt)
            content = response.content.strip()
            
            # Extract JSON
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
        
        return []
    
    def _decompose_email_steps_with_structured_outputs(self, prompt: str) -> List[Dict[str, Any]]:
        """
        Decompose email query steps using structured outputs for reliable extraction.
        
        Uses LangChain's structured output support to ensure consistent,
        type-safe email step decomposition.
        
        Args:
            prompt: Decomposition prompt
            
        Returns:
            List of step dictionaries or empty list if structured outputs fail
        """
        if not self.llm_client:
            return []
        
        try:
            # Try LangChain's unified structured output support
            if hasattr(self.llm_client, 'with_structured_outputs'):
                try:
                    from ...schemas.schemas import EmailStepsSchema
                    
                    # Use EmailStepsSchema for structured output
                    structured_llm = self.llm_client.with_structured_outputs(EmailStepsSchema)
                    
                    # Invoke with structured output guarantee
                    try:
                        response = structured_llm.invoke(prompt)
                    except (TypeError, AttributeError):
                        from langchain_core.messages import HumanMessage
                        messages = [HumanMessage(content=prompt)]
                        response = structured_llm.invoke(messages)
                    
                    # Extract steps from structured response
                    if isinstance(response, EmailStepsSchema):
                        decomposition = response.model_dump()
                    elif isinstance(response, dict):
                        decomposition = response
                    else:
                        decomposition = response.model_dump() if hasattr(response, 'model_dump') else {}
                    
                    steps_data = decomposition.get('steps', [])
                    
                    # Convert to our step format
                    steps = []
                    for step_data in steps_data:
                        if isinstance(step_data, dict):
                            steps.append({
                                "description": step_data.get("description", ""),
                                "operation": step_data.get("operation", ""),
                                "params": step_data.get("params", {})
                            })
                    
                    if steps:
                        logger.info(f"[OK] Email steps decomposed using structured outputs: {len(steps)} steps")
                        return steps
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(f"Structured output email decomposition not available: {e}")
                    return []
        except Exception as e:
            logger.debug(f"Structured output email decomposition failed: {e}")
        
        return []
    
    def _execute_query_step(self, step: Dict[str, Any], tool: BaseTool, user_id: Optional[int], session_id: Optional[str]) -> str:
        """
        Execute a single query step
        
        Args:
            step: Step dictionary with operation and params
            tool: Email tool to execute with
            user_id: Optional user ID
            session_id: Optional session ID
            
        Returns:
            Step execution result
        """
        operation = step.get('operation')
        params = step.get('params', {})
        
        if operation == 'search_emails':
            query_part = params.get('sender', '')
            if 'sender' in params:
                query_part = f"from:{params['sender']}"
            return tool._run(action="search", query=query_part, limit=params.get('limit', DEFAULT_STEP_LIMIT))
        elif operation == 'list_emails':
            return tool._run(action="list", limit=params.get('limit', DEFAULT_STEP_LIMIT))
        else:
            return f"Step completed: {step.get('description', operation)}"
    
    def _execute_single_step(self, query: str, tool: BaseTool, user_id: Optional[int], session_id: Optional[str]) -> str:
        """
        Execute a single-step query using existing logic
        
        Args:
            query: User query string
            tool: Email tool to execute with
            user_id: Optional user ID
            session_id: Optional session ID
            
        Returns:
            Query execution result
        """
        # Use original query directly (no universal enhancement)
        action = self.parser._detect_email_action(query)
        
        action_handlers = {
            "list": lambda: self.parser._handle_list_action(tool, query),
            "search": lambda: self.parser._handle_search_action(tool, query),
            "send": lambda: self.parser._handle_send_action(tool, query),
            "reply": lambda: self.parser._handle_reply_action(tool, query),
        }
        
        handler = action_handlers.get(action, lambda: tool._run(action="list"))
        return handler()
    
    def execute_with_confirmation(self, tool: BaseTool, query: str, classification: Dict[str, Any], 
                                   user_id: Optional[int], session_id: Optional[str]) -> str:
        """
        Execute query autonomously with medium confidence - includes informational confirmation
        
        AUTONOMOUS BEHAVIOR: This method executes the action immediately without waiting for
        user approval. The confirmation message is informational only, not a blocking request.
        The agent operates autonomously and proceeds with execution.
        
        Args:
            tool: Tool to execute with
            query: User query
            classification: LLM classification result
            user_id: Optional user ID
            session_id: Optional session ID
            
        Returns:
            Result with informational confirmation message
        """
        confirmation = self.generate_confirmation_message(query, classification)
        result = self.parser._execute_with_classification(tool, query, classification, user_id, session_id)
        return f"{confirmation}\n\n{result}"
    
    def generate_confirmation_message(self, query: str, classification: Dict[str, Any]) -> str:
        """
        Generate confirmation message for query execution
        
        Args:
            query: User query
            classification: LLM classification result
            
        Returns:
            Confirmation message string
        """
        intent = classification.get('intent', 'process')
        entities = classification.get('entities', {})
        
        msg_parts = [f"[EMAIL] I'll {intent} your emails"]
        
        if entities.get('senders'):
            msg_parts.append(f"from {', '.join(entities['senders'][:2])}")
        
        if entities.get('date_range'):
            date_range = entities['date_range']
            if isinstance(date_range, dict):
                msg_parts.append(f"between {date_range.get('start')} and {date_range.get('end')}")
            elif isinstance(date_range, str):
                msg_parts.append(f"from {date_range}")
        
        return ". ".join(msg_parts) + "."
