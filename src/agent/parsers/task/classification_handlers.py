"""
Task Classification Handlers - Handle task query classification and intent detection

Integrates with:
- schemas.py: TaskClassificationSchema for structured intent classification
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger
from ....ai.prompts import TASK_CREATE_PROMPT
from ....ai.prompts.utils import format_prompt
from .constants import TaskParserConfig

# Schema imports for type-safe classification
try:
    from ...schemas.schemas import TaskClassificationSchema
    HAS_SCHEMAS = True
except ImportError:
    HAS_SCHEMAS = False
    TaskClassificationSchema = Any

logger = setup_logger(__name__)


class TaskClassificationHandlers:
    """Handles task query classification, intent detection, and routing logic"""
    
    def __init__(self, task_parser):
        self.task_parser = task_parser
        self.llm_client = task_parser.llm_client
        self.learning_system = task_parser.learning_system
    
    def detect_task_action(self, query: str) -> str:
        """
        Detect what task action the user wants to perform using LLM-based semantic understanding
        
        Args:
            query: User query
            
        Returns:
            Detected action
        """
        query_lower = query.lower().strip()
        logger.info(f"Detecting action for query: '{query}'")
        
        # PRIORITY 1: Use LLM for semantic understanding FIRST (handles synonyms, context, etc.)
        if self.task_parser.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                import json
                import re
                
                prompt = f"""Analyze this task query and determine the user's intent. Understand semantic meaning, not just literal words.

Query: "{query}"

Understand that:
- "the first one", "first task", "my next task" = referring to a specific task from a list
- "mark done", "complete", "finish", "check off" = same action (complete)
- "delete", "remove", "cancel" = same action (delete)
- "create", "add", "new", "make" = same action (create)
- Synonyms and variations should be understood semantically

Respond with ONLY valid JSON:
{{
    "action": "create" | "complete" | "delete" | "update" | "list" | "search",
    "is_follow_up": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

                response = self.task_parser.llm_client.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    action = result.get('action')
                    confidence = result.get('confidence', 0.7)
                    
                    if action and confidence >= 0.7:
                        logger.info(f"[TASK] LLM detected action: '{query}' → {action} (confidence: {confidence})")
                        return action
            except Exception as e:
                logger.debug(f"[TASK] LLM detection failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based detection (only if LLM unavailable or low confidence)
        # CRITICAL: Check for FOLLOW-UP selections FIRST (before other patterns)
        # These are responses to previous questions like "the first one", "the second one"
        follow_up_patterns = [
            "the first one", "the second one", "the third one", "the fourth one", "the fifth one",
            "first one", "second one", "third one", "fourth one", "fifth one",
            "first", "second", "third", "fourth", "fifth",
            "the one due", "the one that", "the one with",
            "mark the first", "mark the second", "complete the first", "complete the second"
        ]
        
        # Check if this looks like a follow-up to a previous question
        is_follow_up = any(pattern in query_lower for pattern in follow_up_patterns) or \
                      any(word in query_lower for word in ["first", "second", "third", "one", "two", "three"]) and \
                      any(word in query_lower for word in ["mark", "complete", "done", "delete", "remove"])
        
        if is_follow_up:
            # Determine action from context - if it has "mark" or "done", it's complete
            if any(word in query_lower for word in ["mark", "done", "complete", "finish"]):
                logger.info(f"Detected follow-up complete action: '{query}'")
                return "complete"
            elif any(word in query_lower for word in ["delete", "remove"]):
                logger.info(f"Detected follow-up delete action: '{query}'")
                return "delete"
            # Default to complete for follow-ups (most common)
            logger.info(f"Detected follow-up action (defaulting to complete): '{query}'")
            return "complete"
        
        # CRITICAL: Check for UPDATE patterns SECOND (before create) to avoid misclassification
        # Patterns like "add a due date" should be update, not create
        update_patterns = [
            "add a due date", "add due date", "set due date", "add a due date to",
            "change due date", "update due date", "modify due date",
            "add priority", "change priority", "update priority", "set priority",
            "add to task", "change my task", "update my task", "modify my task",
            "edit task", "edit my task", "move task", "reschedule task",
            "update task", "change task", "modify task"
        ]
        
        # Check for update patterns
        for pattern in update_patterns:
            if pattern in query_lower:
                logger.info(f"Matched update pattern: '{pattern}'")
                return "update"
        
        # CRITICAL: Check for create patterns SECOND (after update)
        # These patterns must be checked before other patterns to avoid misclassification
        create_patterns = [
            "create task", "create a task", "create tasks", "create a tasks",
            "add task", "add a task", "add tasks", "add a tasks",
            "add an task", "new task", "make task", "schedule task", 
            "please add", "please create", "please add a task", "please create a task",
            "please add task", "please create task", "please add tasks", "please create tasks",
            "create a task about", "add a task about", "create task about", "add task about"
        ]
        
        # Check for explicit create patterns
        for pattern in create_patterns:
            if pattern in query_lower:
                logger.info(f"Matched create pattern: '{pattern}'")
                return "create"
        
        # Also check for "create" or "add" followed by "task" or "tasks" anywhere in the query
        # This catches variations like "create a task about X" or "add task for Y"
        has_create_or_add = "create" in query_lower or "add" in query_lower
        has_task_word = "task" in query_lower or "tasks" in query_lower
        
        if has_create_or_add and has_task_word:
            # Exclude list queries - these should NOT be classified as create
            list_exclusion_patterns = [
                "what task", "what tasks", "show task", "show tasks", 
                "list task", "list tasks", "my task", "my tasks", 
                "have task", "have tasks", "do i have", "do i have task",
                "what do i have", "show my", "list my", "get my"
            ]
            
            # Only exclude if it's clearly a list query
            is_list_query = any(exclusion in query_lower for exclusion in list_exclusion_patterns)
            
            if not is_list_query:
                logger.info(f"Detected create action: 'create/add' + 'task' pattern")
                return "create"
        
        # Bulk complete patterns (check before single complete)
        if any(phrase in query_lower for phrase in [
            "mark all", "complete all", "finish all", "clear all", 
            "mark all tasks", "complete all tasks", "all done", "all tasks done",
            "mark everything", "clear everything"
        ]):
            return "bulk_complete"
        
        # Single complete patterns - check BEFORE list patterns
        # Handle patterns like "mark task X done", "mark task done", "mark the task done"
        # CRITICAL: Check for "mark" + "done" combination FIRST (most flexible)
        # This catches "mark task X done", "mark task done", "mark the task done", etc.
        if "mark" in query_lower and "done" in query_lower:
            logger.info(f"Detected complete action: 'mark' + 'done' pattern")
            return "complete"
        
        # Check for "complete" or "finish" with "task" (also flexible)
        if ("complete" in query_lower or "finish" in query_lower) and "task" in query_lower:
            logger.info(f"Detected complete action: 'complete/finish' + 'task' pattern")
            return "complete"
        
        # More specific complete patterns
        complete_patterns = [
            "complete task", "mark complete", "finish task", "done with", "mark as done",
            "mark done", "mark it done", "complete it", "finish it",
            "mark task", "mark the task", "mark my task",
            "task done", "task is done", "task's done",
        ]
        
        if any(phrase in query_lower for phrase in complete_patterns):
            logger.info(f"Detected complete action: matched pattern")
            return "complete"
        
        # Delete patterns
        if any(phrase in query_lower for phrase in [
            "delete task", "remove task", "cancel task"
        ]):
            return "delete"
        
        # Note: Update patterns are now checked at the beginning, before create patterns
        
        # Search patterns
        if any(phrase in query_lower for phrase in [
            "find task", "search task", "look for task"
        ]):
            return "search"
        
        # List patterns - must be checked AFTER create and complete patterns
        # Exclude queries that have "mark" + "done" or "complete" + "task" (these are complete actions)
        is_complete_query = ("mark" in query_lower and "done" in query_lower) or \
                           (("complete" in query_lower or "finish" in query_lower) and "task" in query_lower)
        
        if not is_complete_query and any(phrase in query_lower for phrase in [
            "list tasks", "show tasks", "my tasks", "what tasks", "what task",
            "show my tasks", "list my tasks", "get my tasks", "do i have tasks",
            "how many tasks"
        ]):
            return "list"
        
        # Analytics patterns
        if any(phrase in query_lower for phrase in [
            "task analytics", "task insights", "productivity", "progress"
        ]):
            return "analytics"
        
        # Template patterns
        if any(phrase in query_lower for phrase in [
            "task template", "create template", "use template"
        ]):
            return "template"
        
        # Recurring task patterns
        if any(phrase in query_lower for phrase in [
            "recurring task", "repeat task", "daily task", "weekly task"
        ]):
            return "recurring"
        
        # Reminder patterns
        if any(phrase in query_lower for phrase in [
            "reminder", "remind me", "set reminder"
        ]):
            return "reminders"
        
        # Overdue patterns
        if any(phrase in query_lower for phrase in [
            "overdue", "late task", "past due"
        ]):
            return "overdue"
        
        # Use LLM classification if available (skip async in sync context)
        # BUT: Only use LLM if pattern-based detection didn't find a clear match
        # This prevents LLM from overriding clear pattern matches
        if self.task_parser.classifier:
            try:
                # Check if classify_query is async or sync
                import inspect
                classify_method = self.task_parser.classifier.classify_query
                if inspect.iscoroutinefunction(classify_method):
                    # Skip async classification in sync context - use pattern-based fallback
                    logger.debug("Skipping async classify_query in sync context, using pattern-based detection")
                else:
                    # Sync version - call directly
                    classification = classify_method(query)
                    intent = classification.get('intent', 'list')
                    confidence = classification.get('confidence', 0.5)
                    logger.info(f"Detected action via NLP: {intent} (confidence: {confidence})")
                    
                    # Map LLM intents to actions
                    intent_to_action = {
                        'create': 'create',
                        'add': 'create',
                        'new': 'create',
                        'list': 'list',
                        'show': 'list',
                        'complete': 'complete',
                        'finish': 'complete',
                        'delete': 'delete',
                        'remove': 'delete',
                        'search': 'search',
                        'find': 'search',
                        'analytics': 'analytics',
                        'insights': 'analytics'
                    }
                    
                    llm_action = intent_to_action.get(intent, 'list')
                    
                    # CRITICAL: If LLM says 'list' but query has create keywords, trust the patterns
                    if llm_action == 'list' and has_create_or_add and has_task_word:
                        logger.warning(f"LLM misclassified create query as 'list', using pattern-based 'create'")
                        return "create"
                    
                    return llm_action
                
            except Exception as e:
                logger.warning(f"NLP classification failed, using fallback: {e}")
        
        # Default fallback - but check one more time for create patterns
        if has_create_or_add and has_task_word:
            logger.info("Default fallback: detected create pattern")
            return "create"
        
        return "list"
    
    def detect_explicit_task_action(self, query_lower: str) -> Optional[str]:
        """
        Detect explicit task action patterns before LLM classification
        """
        # Create patterns (highest priority)
        if any(phrase in query_lower for phrase in [
            "create task", "add task", "new task", "make task", "add a task"
        ]):
            return "create"
        
        # Complete patterns
        if any(phrase in query_lower for phrase in [
            "complete task", "mark complete", "finish task", "mark as done"
        ]):
            return "complete"
        
        # Delete patterns
        if any(phrase in query_lower for phrase in [
            "delete task", "remove task", "cancel task"
        ]):
            return "delete"
        
        # List patterns
        if any(phrase in query_lower for phrase in [
            "list tasks", "show tasks", "my tasks", "what tasks do i have"
        ]):
            return "list"
        
        # Search patterns
        if any(phrase in query_lower for phrase in [
            "find task", "search task", "look for task"
        ]):
            return "search"
        
        return None
    
    def route_with_confidence(
        self,
        query: str,
        query_lower: str,
        llm_intent: Optional[str],
        llm_confidence: float,
        semantic_action: Optional[str],
        explicit_action: Optional[str],
        classification: Optional[Dict[str, Any]]
    ) -> str:
        """
        Enhanced confidence-based routing for task intents
        """
        # Map LLM intent to action
        intent_to_action = {
            'create': 'create',
            'add': 'create',
            'list': 'list',
            'show': 'list',
            'complete': 'complete',
            'delete': 'delete',
            'search': 'search',
            'analytics': 'analytics'
        }
        
        llm_action = intent_to_action.get(llm_intent, 'list') if llm_intent else None
        
        # High confidence: Trust LLM
        if llm_confidence > TaskParserConfig.HIGH_CONFIDENCE_THRESHOLD:
            if explicit_action and explicit_action != llm_action:
                if self.is_critical_task_misclassification(query_lower, llm_action, explicit_action):
                    logger.warning(f"High confidence LLM ({llm_confidence}) overridden by critical pattern")
                    return explicit_action
            
            if semantic_action == llm_action:
                logger.info(f"Semantic match validates LLM classification")
                return llm_action
            
            return llm_action or 'list'
        
        # Medium confidence: Use patterns as tie-breaker
        elif llm_confidence >= TaskParserConfig.DEFAULT_CONFIDENCE_THRESHOLD:
            if explicit_action:
                logger.info(f"Medium confidence: using explicit pattern as tie-breaker")
                return explicit_action
            
            if semantic_action:
                logger.info(f"Medium confidence: using semantic match")
                return semantic_action
            
            return llm_action or 'list'
        
        # Low confidence: Trust patterns more
        else:
            if explicit_action:
                logger.info(f"Low confidence: trusting explicit pattern")
                return explicit_action
            
            if semantic_action:
                logger.info(f"Low confidence: trusting semantic pattern")
                return semantic_action
            
            return llm_action or 'list'
    
    def is_critical_task_misclassification(self, query_lower: str, llm_action: Optional[str], pattern_action: str) -> bool:
        """
        Check if this is a critical misclassification that must be corrected
        """
        critical_cases = [
            # Create queries misclassified as list
            (['create task', 'add task', 'new task'], 'list', 'create'),
            # Complete queries misclassified as create
            (['complete task', 'mark complete'], 'create', 'complete'),
            # Delete queries misclassified as create
            (['delete task', 'remove task'], 'create', 'delete'),
        ]
        
        for patterns, wrong_action, correct_action in critical_cases:
            if pattern_action == correct_action and llm_action == wrong_action:
                if any(pattern in query_lower for pattern in patterns):
                    logger.warning(f"Critical misclassification detected: {wrong_action} → {correct_action}")
                    return True
        
        return False
    
    def validate_classification(self, query: str, action: str, classification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Self-validation: LLM validates its own classification for task queries
        """
        if not self.llm_client:
            return {'should_correct': False, 'corrected_action': action}
        
        try:
            validation_prompt = f"""
Validate this task classification:

Query: "{query}"
Detected Action: {action}
Classification: {json.dumps(classification, indent=2)}

Is this classification correct? Consider:
1. Does the action match the user's intent?
2. Are the extracted entities accurate?
3. Are there any obvious mistakes?

Respond with JSON:
{{
    "is_correct": true/false,
    "corrected_action": "action_if_incorrect",
    "reasoning": "brief explanation"
}}
"""

            try:
                from langchain_core.messages import HumanMessage
            except ImportError:
                from langchain.schema import HumanMessage
            
            response = self.llm_client.invoke([HumanMessage(content=validation_prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            validation = json.loads(response_text)
            
            if not validation.get('is_correct', True):
                corrected_action = validation.get('corrected_action', action)
                logger.info(f"Self-validation corrected: {action} → {corrected_action}")
                return {
                    'should_correct': True,
                    'corrected_action': corrected_action,
                    'reasoning': validation.get('reasoning', '')
                }
            
            return {'should_correct': False, 'corrected_action': action}
            
        except Exception as e:
            logger.warning(f"Self-validation failed: {e}")
            return {'should_correct': False, 'corrected_action': action}
    
    def classify_task_query_with_enhancements(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Enhanced task classification with few-shot learning and chain-of-thought reasoning.
        
        Tries structured output with TaskClassificationSchema first, then falls back to JSON.
        """
        if not self.llm_client:
            return None
        
        # Try structured output with schema first if available
        if HAS_SCHEMAS and hasattr(self.llm_client, 'with_structured_output'):
            try:
                result = self.classify_with_schema(query)
                if result:
                    logger.info("[SCHEMA] Successfully classified with TaskClassificationSchema")
                    return result
            except Exception as e:
                logger.warning(f"[SCHEMA] Structured classification failed: {e}, falling back to JSON")
        
        # Fallback to JSON-based classification
        try:
            # Get similar successful queries for few-shot learning
            similar_examples = []
            if self.learning_system:
                similar_examples = self.learning_system.get_similar_successes(query, limit=TaskParserConfig.DEFAULT_SIMILAR_EXAMPLES_LIMIT)
            
            # Build few-shot examples section
            examples_section = ""
            if similar_examples:
                examples_section = "\n\nHere are examples of similar successful queries:\n"
                for i, example in enumerate(similar_examples, 1):
                    examples_section += f"\nExample {i}:\n"
                    examples_section += f"Query: \"{example['query']}\"\n"
                    examples_section += f"Intent: {example['intent']}\n"
                    if example.get('classification'):
                        entities = example['classification'].get('entities', {})
                        if entities:
                            examples_section += f"Entities: {entities}\n"
            
            prompt = f"""You are Clavr, an intelligent task assistant. Analyze this task query and extract structured information.{examples_section}

Query: "{query}"

IMPORTANT: Understand task queries including:
- Creation: "create task to buy groceries", "add reminder for meeting"
- Completion: "mark task as done", "complete the shopping task"
- Listing: "show my tasks", "what tasks do I have"
- Deletion: "delete the old task", "remove completed tasks"
- Search: "find tasks about project", "search for overdue tasks"

Think through your classification step by step:

Step 1: What is the user trying to do?
- Create a new task? → "create"
- Complete an existing task? → "complete"
- List/view tasks? → "list"
- Delete a task? → "delete"
- Search for tasks? → "search"
- Get analytics/insights? → "analytics"

Step 2: Extract key information:
- Task description or title
- Due date or deadline
- Priority level
- Category or project

Step 3: Determine confidence level:
- High (0.85-1.0): Very clear intent
- Medium (0.6-0.85): Mostly clear
- Low (<0.6): Unclear or ambiguous

Return ONLY valid JSON:
{{
    "intent": "create",
    "confidence": 0.9,
    "reasoning": "User wants to create a new task",
    "entities": {{
        "description": "task description",
        "due_date": "date expression",
        "priority": "high/medium/low",
        "category": "work/personal/etc"
    }},
    "limit": 10
}}"""

            try:
                from langchain_core.messages import HumanMessage
            except ImportError:
                from langchain.schema import HumanMessage
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group(0)
            
            classification = json.loads(response_text)
            
            # Normalize classification
            return {
                'intent': classification.get('intent', 'list'),
                'confidence': classification.get('confidence', 0.5),
                'reasoning': classification.get('reasoning', ''),
                'entities': classification.get('entities', {}),
                'limit': classification.get('limit', TaskParserConfig.DEFAULT_TASK_LIMIT)
            }
            
        except Exception as e:
            logger.warning(f"Enhanced task classification failed: {e}")
            return None
    
    def classify_with_schema(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Classify task query using TaskClassificationSchema with structured outputs.
        
        This method uses the LLM's structured output capability to ensure
        type-safe, validated classification results.
        
        Args:
            query: User query
            
        Returns:
            Classification dict matching TaskClassificationSchema or None
        """
        if not self.llm_client or not HAS_SCHEMAS:
            return None
        
        try:
            prompt = f"""Classify this task query and extract structured information: "{query}"

Analyze the query and determine:
1. intent: The task action (list, create, update, delete, complete, search, prioritize)
2. confidence: How certain you are (0.0-1.0)
3. entities: Extracted information like title, description, due_date, priority, tags, assignee
4. filters: Filters to apply (completed, pending, overdue, today, high_priority, etc.)
5. limit: Maximum number of results (default: 10)

CRITICAL RULES:
- "create task", "add task", "new task" → intent: "create"
- "list tasks", "show tasks", "my tasks" → intent: "list"  
- "complete task", "mark done", "finish task" → intent: "complete"
- "delete task", "remove task" → intent: "delete"
- "find tasks", "search tasks" → intent: "search"

Examples:
- "Create a task to buy groceries" → intent="create", entities={{"title": "buy groceries"}}
- "Show my tasks for today" → intent="list", filters=["today"]
- "Mark the shopping task as complete" → intent="complete", entities={{"title": "shopping"}}
- "Find high priority tasks" → intent="search", filters=["high_priority"]
"""
            
            # Use structured output
            structured_llm = self.llm_client.with_structured_output(TaskClassificationSchema)
            result = structured_llm.invoke(prompt)
            
            # Convert Pydantic model to dict
            return {
                'intent': result.intent,
                'confidence': result.confidence,
                'entities': result.entities,
                'filters': result.filters,
                'limit': result.limit
            }
            
        except Exception as e:
            logger.warning(f"Schema-based task classification failed: {e}")
            return None 
