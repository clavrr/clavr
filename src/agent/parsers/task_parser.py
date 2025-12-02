"""
Task Parser - Refactored with modular handlers

This parser understands natural language task queries and converts them into
structured task operations. It provides:

- Intent classification (create, list, complete, delete, search, etc.)
- Entity extraction (descriptions, due dates, priorities, categories)
- Advanced date/time parsing with natural language support
- Conversational response generation
- Task analytics and insights

The parser uses LLM-powered classification when available, falling back to
pattern-based parsing for reliability.

Enhanced with Superior NLU Approach:
- Semantic pattern matching with Gemini embeddings
- Confidence-based routing
- Learning system for continuous improvement
- Few-shot learning and chain-of-thought reasoning
- Self-validation and correction
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool

from .base_parser import BaseParser
from ...utils.logger import setup_logger
from ...core.calendar.utils import (
    parse_datetime_with_timezone,
    format_datetime_for_calendar,
    DEFAULT_DURATION_MINUTES
)
from ...ai.prompts import TASK_CREATE_SYSTEM, TASK_CREATE_PROMPT
from ...ai.prompts.utils import format_prompt
from ..intent import (
    TASK_QUESTION_PATTERNS, TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS,
    TASK_ANALYSIS_PATTERNS, TASK_COMPLETION_PATTERNS
)

# Import extracted NLU components from task module
from .task.semantic_matcher import TaskSemanticPatternMatcher
from .task.learning_system import TaskLearningSystem

# Import handler modules
from .task.classification_handlers import TaskClassificationHandlers
from .task.action_handlers import TaskActionHandlers
from .task.analytics_handlers import TaskAnalyticsHandlers
from .task.creation_handlers import TaskCreationHandlers
from .task.management_handlers import TaskManagementHandlers
from .task.query_processing_handlers import TaskQueryProcessingHandlers
from .task.utility_handlers import TaskUtilityHandlers

logger = setup_logger(__name__)


class TaskParser(BaseParser):
    """
    Enhanced Task Parser with Superior NLU
    
    Modular architecture with specialized handlers:
    - Classification: Intent detection and confidence-based routing
    - Action: Task-specific action handling
    - Analytics: Task analysis and productivity insights  
    - Creation: Task creation and entity extraction
    - Management: Task operations (complete, delete, search, etc.)
    - QueryProcessing: Query execution and response generation
    - Utility: Common helper functions
    """
    
    def __init__(self, rag_service=None, memory=None, config=None, user_first_name: Optional[str] = None, workflow_emitter: Optional[Any] = None):
        super().__init__(rag_service, memory, config)
        self.name = "task"
        self.config = config
        self.user_first_name = user_first_name
        self.workflow_emitter = workflow_emitter  # Store workflow emitter for event emission
        
        # Add NLP utilities if config provided (following EmailParser pattern)
        if config:
            try:
                from ...ai.query_classifier import QueryClassifier
                from ...utils import FlexibleDateParser
                from ...ai.llm_factory import LLMFactory
                
                self.classifier = QueryClassifier(config)
                self.date_parser = FlexibleDateParser(config)
                try:
                    from .task.constants import TaskParserConfig
                    # Initialize LLM client with higher max_tokens to prevent truncation of conversational responses
                    self.llm_client = LLMFactory.get_llm_for_provider(
                        config, 
                        temperature=TaskParserConfig.LLM_TEMPERATURE, 
                        max_tokens=TaskParserConfig.LLM_MAX_TOKENS
                    )
                    logger.info(f"LLM client initialized for conversational task responses (max_tokens={TaskParserConfig.LLM_MAX_TOKENS} to prevent truncation)")
                except Exception as e:
                    self.llm_client = None
                    logger.warning(f"LLM not available for task parser: {e}, using pattern-based parsing")
            except Exception as e:
                logger.warning(f"Failed to initialize NLP utilities: {e}")
                self.classifier = None
                self.date_parser = None
                self.llm_client = None
        else:
            self.classifier = None
            self.date_parser = None
            self.llm_client = None
            logger.info("Task parser initialized without config - using pattern-based parsing")
        
        # Initialize enhanced NLU components
        # Pass config to semantic matcher so it can use Gemini embeddings if available
        self.semantic_matcher = TaskSemanticPatternMatcher(config=config)
        self.learning_system = TaskLearningSystem(memory=memory)
        
        # Initialize handler modules
        self.classification_handlers = TaskClassificationHandlers(self)
        self.action_handlers = TaskActionHandlers(self)
        self.analytics_handlers = TaskAnalyticsHandlers(self)
        self.creation_handlers = TaskCreationHandlers(self)
        self.management_handlers = TaskManagementHandlers(self)
        self.query_processing_handlers = TaskQueryProcessingHandlers(self)
        self.utility_handlers = TaskUtilityHandlers(self)
        
        logger.info("All task handler modules initialized successfully")
    
    def get_supported_tools(self) -> List[str]:
        """Return list of tool names this parser supports"""
        return ['task']
    
    def parse_query_to_params(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse task query into structured parameters WITHOUT executing the tool
        
        Args:
            query: User query
            user_id: Optional user ID for context
            session_id: Optional session ID for context
            
        Returns:
            Dictionary with:
                - action: str (e.g., 'create', 'list', 'complete', 'delete', 'search')
                - entities: Dict[str, Any] (e.g., description, due_date, priority, category)
                - confidence: float (0.0-1.0)
                - metadata: Dict[str, Any] (suggestions, detected patterns, etc.)
        """
        try:
            logger.info(f"[TASK] TaskParser.parse_query_to_params called with query: '{query}'")
            
            # Extract actual query from conversation context
            actual_query = self.query_processing_handlers.extract_actual_query(query)
            
            # Detect task action using classification handlers
            action = self.classification_handlers.detect_task_action(actual_query)
            logger.info(f"[TASK] Detected action: {action}")
            
            # Extract entities based on action
            entities = self._extract_entities_for_action(actual_query, action)
            
            # Calculate confidence (simple implementation)
            confidence = self._calculate_confidence(actual_query, action, entities)
            
            # Generate metadata (simple implementation)
            metadata = self._generate_metadata(actual_query, action, entities)
            
            return {
                "action": action,
                "entities": entities,
                "confidence": confidence,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"[TASK] Error in parse_query_to_params: {e}")
            return {
                "action": "error",
                "entities": {},
                "confidence": 0.0,
                "metadata": {"error": str(e)}
            }
    
    def _extract_entities_for_action(self, query: str, action: str) -> Dict[str, Any]:
        """Extract entities relevant to the detected action"""
        entities = {}
        
        if action == "create":
            # Extract task description using delegation method with proper parameters
            action_words = ['create', 'add', 'make', 'schedule', 'remind']
            entities['description'] = self.creation_handlers._extract_task_description(query, action_words)
            
            # Parse date using date parser if available
            if self.date_parser:
                try:
                    date_result = self.date_parser.parse(query)
                    if date_result:
                        entities['due_date'] = date_result
                except Exception as e:
                    logger.debug(f"Date parsing failed: {e}")
            
            # Extract priority using creation handlers
            priority = self.creation_handlers._extract_priority(query)
            if priority:
                entities['priority'] = priority
            
            # Extract category/tags using creation handlers
            category = self.creation_handlers._extract_category(query)
            if category:
                entities['category'] = category
                
        elif action == "list":
            # Extract filters
            priority = self.creation_handlers._extract_priority(query)
            if priority:
                entities['priority'] = priority
                
        elif action == "complete":
            # Extract task ID or search term
            # Simplified - just use query as search term
            entities['search_term'] = query
                
        elif action == "search":
            # Extract search query using delegation method
            # Note: _extract_search_term exists but needs signature update
            entities['search_term'] = query  # Simplified for now
            
        return entities
    
    def _calculate_confidence(self, query: str, action: str, entities: Dict[str, Any]) -> float:
        """Calculate confidence score for the parsing result"""
        confidence = 0.5  # Base confidence
        
        query_lower = query.lower()
        task_keywords = ['task', 'tasks', 'todo', 'reminder', 'deadline']
        has_task_keywords = any(keyword in query_lower for keyword in task_keywords)
        
        # CRITICAL: For explicit task list queries like "what's on my tasks", give high confidence
        explicit_task_list_patterns = [
            "what's on my tasks", "what's on my task", "on my tasks", "on my task",
            "what tasks do i have", "tasks do i have", "my tasks", "show my tasks",
            "list my tasks", "get my tasks", "do i have tasks"
        ]
        is_explicit_task_query = any(pattern in query_lower for pattern in explicit_task_list_patterns)
        
        if is_explicit_task_query:
            # Very high confidence for explicit task queries
            confidence = 0.9
            logger.info(f"[TASK] High confidence for explicit task query: '{query}'")
        else:
            # Increase confidence if action is explicit
            explicit_actions = ['create', 'complete', 'delete', 'search']
            if action in explicit_actions:
                confidence += 0.2
            
            # Increase confidence if entities were extracted
            if entities:
                confidence += 0.2
            
            # Increase confidence if query contains task keywords
            if has_task_keywords:
                confidence += 0.1
        
        return min(1.0, confidence)
    
    def _generate_metadata(self, query: str, action: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Generate metadata for the parsing result"""
        return {
            'action': action,
            'entities': entities,
            'query': query,
            'parser': 'task_parser'
        }

    def parse_query(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """
        Parse task-related query with enhanced NLU approach
        
        Uses multiple approaches for robust intent detection:
        1. LLM-powered classification (primary)
        2. Semantic pattern matching (secondary) 
        3. Pattern-based fallback (tertiary)
        
        Args:
            query: User query
            tool: Task tool
            user_id: User ID (optional)
            session_id: Session ID (optional)
            
        Returns:
            Conversational task response
        """
        logger.info(f"[TASK] Processing query: {query}")
        
        try:
            # Store session info for potential feedback learning
            self.current_session = {
                "user_id": user_id,
                "session_id": session_id,
                "query": query,
                "timestamp": datetime.now()
            }
            
            # Step 1: Enhanced Action Detection with Confidence Routing
            action = self._detect_task_action(query)
            logger.info(f"[TASK] Detected action: {action}")
            
            # Step 2: Try LLM Classification (Primary approach)
            classification = self._classify_task_query_with_enhancements(query)
            
            if classification:
                # Validate and potentially correct classification
                validated_classification = self._validate_classification(query, action, classification)
                
                if validated_classification:
                    logger.info(f"[TASK] Using LLM classification: {validated_classification}")
                    result = self._execute_task_with_classification(tool, query, validated_classification, action)
                    
                    # Learn from this interaction
                    self.learning_system.record_classification_result(
                        query=query,
                        predicted_action=action,
                        llm_classification=validated_classification,
                        success=not result.startswith("[ERROR]")
                    )
                    
                    return result
            
            # Step 3: Fallback to pattern-based execution
            logger.info("[TASK] Using pattern-based execution")
            return self._execute_action_by_pattern(tool, query, action)
            
        except Exception as e:
            logger.error(f"Task query parsing failed: {e}")
            return f"[ERROR] Failed to process task query: {str(e)}"
    
    # ============================================================================
    # DELEGATION METHODS - Delegate to appropriate handlers
    # ============================================================================
    
    def _detect_task_action(self, query: str) -> str:
        """Delegate to classification handlers"""
        return self.classification_handlers.detect_task_action(query)
    
    def _detect_explicit_task_action(self, query_lower: str) -> Optional[str]:
        """Delegate to classification handlers"""
        return self.classification_handlers.detect_explicit_task_action(query_lower)
    
    def _validate_classification(self, query: str, action: str, classification: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to classification handlers"""
        return self.classification_handlers.validate_classification(query, action, classification)
    
    def _classify_task_query_with_enhancements(self, query: str) -> Optional[Dict[str, Any]]:
        """Delegate to classification handlers"""
        return self.classification_handlers.classify_task_query_with_enhancements(query)
    
    def _execute_task_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any], action: str) -> str:
        """Delegate to query processing handlers"""
        return self.query_processing_handlers.execute_task_with_classification(tool, query, classification, action)
    
    def _parse_and_create_task_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any]) -> str:
        """Delegate to creation handlers"""
        return self.creation_handlers.parse_and_create_task_with_classification(tool, query, classification)
    
    def _execute_action_by_pattern(self, tool: BaseTool, query: str, action: str) -> str:
        """
        Execute task action using pattern-based routing
        
        Routes to appropriate handler based on action type.
        """
        try:
            if action == "create":
                return self.creation_handlers.handle_create_action(tool, query)
            elif action == "list":
                return self.management_handlers.handle_list_action(tool, query)
            elif action == "complete":
                return self.management_handlers.handle_complete_action(tool, query)
            elif action == "delete":
                return self.management_handlers.handle_delete_action(tool, query)
            elif action == "search":
                return self.management_handlers.handle_search_action(tool, query)
            elif action == "analytics" or action == "analyze":
                return self.analytics_handlers.handle_analytics_action(tool, query)
            elif action == "template":
                return self.management_handlers.handle_template_action(tool, query)
            elif action == "recurring":
                return self.management_handlers.handle_recurring_action(tool, query)
            elif action == "reminders":
                return self.management_handlers.handle_reminders_action(tool, query)
            elif action == "overdue":
                return self.management_handlers.handle_overdue_action(tool, query)
            elif action == "subtasks":
                return self.management_handlers.handle_subtasks_action(tool, query)
            elif action == "bulk":
                return self.management_handlers.handle_bulk_action(tool, query)
            else:
                logger.warning(f"Unknown task action: {action}, defaulting to list")
                return self.management_handlers.handle_list_action(tool, query)
        except Exception as e:
            logger.error(f"Error executing task action '{action}': {e}", exc_info=True)
            return f"[ERROR] Failed to execute task action: {str(e)}"
