"""
Calendar Parser - Handles calendar-specific query parsing and execution

This parser understands natural language calendar queries and converts them into
structured calendar operations. It provides:

- Intent classification (list, create, update, delete, search, etc.)
- Entity extraction (titles, times, attendees, locations)
- Conflict detection and resolution
- Conversational response generation
- Advanced date/time parsing with timezone awareness

The parser uses LLM-powered classification when available, falling back to
pattern-based parsing for reliability.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import pytz  # Used throughout for timezone handling
import numpy as np
from langchain.tools import BaseTool

from .base_parser import BaseParser
from ...utils.logger import setup_logger

# Import extracted calendar modules
from .calendar.semantic_matcher import CalendarSemanticPatternMatcher, DEFAULT_SEMANTIC_THRESHOLD
from .calendar.learning_system import CalendarLearningSystem
from .calendar.event_handlers import CalendarEventHandlers
from .calendar.list_search_handlers import CalendarListSearchHandlers
from .calendar.action_classifiers import CalendarActionClassifiers
from .calendar.utility_handlers import CalendarUtilityHandlers
from .calendar.advanced_handlers import CalendarAdvancedHandlers

from ...core.calendar.utils import (
    parse_datetime_with_timezone,
    format_datetime_for_calendar,
    get_user_timezone,
    get_day_boundaries,
    parse_event_time,
    find_conflicts,
    format_event_time_display,
    calculate_ordinal_day_date,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_DAYS_AHEAD
)
from ...ai.prompts import CALENDAR_CREATE_SYSTEM, CALENDAR_CREATE_PROMPT
from ..intent import CALENDAR_QUESTION_PATTERNS
from ..schemas.schemas import CalendarClassificationSchema

logger = setup_logger(__name__)

# Try to import sentence transformers for semantic matching
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not available - semantic matching will be disabled")


class CalendarParser(BaseParser):
    """
    Calendar parser for handling calendar-related queries
    
    Supports:
    - Calendar event listing and searching
    - Calendar event creation and scheduling
    - Calendar event management operations
    - RAG-enhanced calendar understanding
    - LLM-powered intent classification
    - Advanced date/time parsing
    
    NOTE: This parser handles ONLY calendar operations (meetings, events, scheduling).
    Task-related queries (tasks, todos, reminders, deadlines) are handled by TaskParser.
    The orchestration layer is responsible for routing queries to the correct parser.
    """
    
    def __init__(self, rag_service=None, memory=None, config=None, workflow_emitter: Optional[Any] = None):
        super().__init__(rag_service, memory, config)
        self.name = "calendar"
        self.config = config
        self.workflow_emitter = workflow_emitter  # Store workflow emitter for event emission
        
        # CRITICAL: Always initialize date parser - it's essential for time-of-day filtering
        # Initialize date parser FIRST, even if config is None (will use defaults)
        self.date_parser = None
        try:
            from ...utils import FlexibleDateParser
            # Try with config first
            if config:
                try:
                    self.date_parser = FlexibleDateParser(config)
                    logger.info("[OK] FlexibleDateParser initialized with config")
                except Exception as e:
                    logger.warning(f"FlexibleDateParser failed with config: {e}, trying without config")
                    # Fallback: try without config (will use UTC timezone)
                    try:
                        self.date_parser = FlexibleDateParser(None)
                        logger.info("[OK] FlexibleDateParser initialized without config (using UTC)")
                    except Exception as e2:
                        logger.error(f"FlexibleDateParser failed even without config: {e2}")
                        self.date_parser = None
            else:
                # No config, but still try to initialize (will use UTC)
                try:
                    self.date_parser = FlexibleDateParser(None)
                    logger.info("[OK] FlexibleDateParser initialized without config (using UTC)")
                except Exception as e:
                    logger.error(f"FlexibleDateParser failed without config: {e}")
                    self.date_parser = None
        except ImportError as e:
            logger.error(f"CRITICAL: Cannot import FlexibleDateParser: {e}")
            self.date_parser = None
        except Exception as e:
            logger.error(f"CRITICAL: Unexpected error initializing FlexibleDateParser: {e}", exc_info=True)
            self.date_parser = None
        
        # Verify date parser is available
        if self.date_parser is None:
            logger.error("[CRITICAL] FlexibleDateParser is NOT available! Time-of-day filtering will NOT work!")
            logger.error("[CRITICAL] Calendar queries with 'morning', 'afternoon', 'evening' will return ALL events for the day!")
        else:
            logger.info("[OK] FlexibleDateParser is available and ready for time-of-day filtering")
        
        # Add NLP utilities if config provided (following TaskParser pattern)
        if config:
            try:
                from ...ai.query_classifier import QueryClassifier
                from ...ai.llm_factory import LLMFactory
                
                self.classifier = QueryClassifier(config)
                
                # Initialize LLM client (critical for conversational responses)
                # Use higher max_tokens to prevent truncation of conversational responses
                from .base_parser import DEFAULT_LLM_TEMPERATURE, DEFAULT_LLM_MAX_TOKENS
                try:
                    self.llm_client = LLMFactory.get_llm_for_provider(config, temperature=DEFAULT_LLM_TEMPERATURE, max_tokens=DEFAULT_LLM_MAX_TOKENS)
                    logger.info(f"LLM client initialized for conversational calendar responses (max_tokens={DEFAULT_LLM_MAX_TOKENS} to prevent truncation)")
                except Exception as e:
                    self.llm_client = None
                    logger.warning(f"LLM not available for calendar parser: {e}, using pattern-based parsing")
            except Exception as e:
                logger.warning(f"Failed to initialize NLP utilities: {e}")
                self.classifier = None
                if self.llm_client is None:
                    self.llm_client = None
        else:
            self.classifier = None
            self.llm_client = None
            logger.info("Calendar parser initialized without config - using pattern-based parsing")
        
        # Initialize enhanced NLU components (using extracted modules)
        # Pass config to semantic matcher so it can use Gemini embeddings if available
        self.semantic_matcher = CalendarSemanticPatternMatcher(config=config)
        self.learning_system = CalendarLearningSystem(memory=memory)
        
        # Initialize event handlers module
        self.event_handlers = CalendarEventHandlers(self)
        
        # Initialize list/search handlers module
        self.list_search_handlers = CalendarListSearchHandlers(self)
        
        # Initialize action classifiers module
        self.action_classifiers = CalendarActionClassifiers(self)
        
        # Initialize utility handlers module
        self.utility_handlers = CalendarUtilityHandlers(self)
        
        # Initialize advanced handlers module
        self.advanced_handlers = CalendarAdvancedHandlers(self)
    
    def get_supported_tools(self) -> List[str]:
        """Return list of tool names this parser supports"""
        return ['calendar']
    
    # NOTE: Task query detection has been removed. Task routing is handled by the orchestration layer.
    # Calendar parser should only receive calendar-related queries (events, meetings, scheduling).
    # If task queries are received, they should be rejected at the orchestration layer, not here.
    
    def parse_query(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """
        Enhanced parse_query with confidence-based routing and semantic matching.
        
        Uses a hybrid approach:
        1. Check learned corrections first
        2. Get LLM classification with confidence
        3. Get semantic pattern match (handles paraphrases)
        4. Get exact pattern match (for critical cases)
        5. Route based on confidence levels
        6. Self-validate if needed
        
        Args:
            query: User query
            tool: Calendar tool to execute with
            user_id: User ID
            session_id: Session ID
            
        Returns:
            Tool execution result
        """
        if not self.validate_tool(tool):
            # Use LLM to generate natural error message
            if self.llm_client:
                try:
                    from langchain_core.messages import HumanMessage
                    from ...ai.prompts import CALENDAR_UNAVAILABLE_PROMPT
                    
                    response = self.llm_client.invoke([HumanMessage(content=CALENDAR_UNAVAILABLE_PROMPT)])
                    if hasattr(response, 'content'):
                        return response.content.strip()
                except Exception:
                    pass
            return "I'm having trouble accessing your calendar right now. Please try again in a moment."
        
        try:
            logger.info(f"[CAL] CalendarParser.parse_query called with query: '{query}'")
            
            # ENHANCED: Check learned corrections first
            learned_intent = self.learning_system.get_learned_intent(query)
            if learned_intent:
                logger.info(f"[ENHANCED] Using learned intent: {learned_intent}")
                # Use learned intent but still get LLM for entity extraction
                if self.classifier:
                    try:
                        classification = self.action_classifiers.classify_calendar_query(query)
                        classification['intent'] = learned_intent
                        classification['confidence'] = 0.95  # High confidence from learning
                        return self.action_classifiers.execute_calendar_with_classification(tool, query, classification, learned_intent)
                    except Exception as e:
                        logger.warning(f"Failed to use learned intent with LLM: {e}")
            
            # ENHANCED: Get semantic pattern match (handles paraphrases)
            semantic_action = self.semantic_matcher.match_semantic(query, threshold=DEFAULT_SEMANTIC_THRESHOLD)
            
            # CRITICAL: If query contains schedule/create keywords, NEVER route to conflict analysis
            is_schedule_query = any(phrase in query.lower() for phrase in [
                "schedule", "create", "book", "add to calendar", "new event", "new meeting"
            ])
            
            # First, check for explicit calendar-specific patterns (priority over LLM)
            explicit_action = self.action_classifiers.detect_explicit_calendar_action(query.lower())
            
            # Override: If it's a schedule query but was detected as something else, force create
            if is_schedule_query and explicit_action and explicit_action != "create":
                logger.warning(f"[CAL] OVERRIDE: Query '{query}' is a schedule query but detected as '{explicit_action}' - forcing create")
                explicit_action = "create"
            
            # ENHANCED: Get LLM classification with confidence
            llm_intent = None
            llm_confidence = 0.0
            classification = None
            
            if self.classifier:
                try:
                    classification = self.action_classifiers.classify_calendar_query(query)
                    llm_confidence = classification.get('confidence', 0.5)
                    llm_intent = classification.get('intent', 'list')
                    logger.info(f"[ENHANCED] LLM classification: {llm_intent} (confidence: {llm_confidence})")
                except Exception as e:
                    logger.warning(f"LLM classification failed: {e}")
            
            # ENHANCED: Confidence-based routing
            action = self.action_classifiers.route_with_confidence(
                query=query,
                query_lower=query.lower(),
                llm_intent=llm_intent,
                llm_confidence=llm_confidence,
                semantic_action=semantic_action,
                explicit_action=explicit_action,
                is_schedule_query=is_schedule_query,
                classification=classification
            )
            
            logger.info(f"[ENHANCED] Final routed action: {action}")
            
            # ENHANCED: Self-validation for medium confidence
            if 0.6 <= llm_confidence < 0.85 and classification:
                validated = self.action_classifiers.validate_classification(query, action, classification)
                if validated.get('should_correct'):
                    action = validated.get('corrected_action', action)
                    logger.info(f"[ENHANCED] Self-corrected to: {action}")
            
            # Execute with classification if available
            if classification:
                result = self.action_classifiers.execute_calendar_with_classification(tool, query, classification, action)
                # Record success for learning (only if execution was successful)
                try:
                    if result and not any(err in result.lower() for err in ['error', 'failed', 'not found']):
                        self.learning_system.record_success(query, action, classification)
                except Exception as e:
                    logger.debug(f"Failed to record success: {e}")
                # Format response conversationally
                return self.format_response_conversationally(result, query)
            
            # Fallback to pattern-based approach
            query = self.enhance_query(query)
            action = self.action_classifiers.detect_calendar_action(query)
            
            logger.info(f"Detected calendar action: {action}")
            
            # Execute appropriate action and format conversationally
            result = None
            if action == "analyze_conflicts":
                # Double-check: only route to conflict analysis if explicitly requested
                query_lower = query.lower()
                if not any(word in query_lower for word in ["conflict", "conflicts", "overlap", "overlapping", "double booking"]):
                    logger.warning(f"[CAL] Query '{query}' was routed to analyze_conflicts but has no conflict keywords - redirecting")
                    # Check if it's a create/schedule query
                    if any(phrase in query_lower for phrase in ["schedule", "create", "book", "add to calendar"]):
                        action = "create"
                        logger.info("[CAL] Redirected to create action")
                    else:
                        action = "list"
                        logger.info("[CAL] Redirected to list action")
                else:
                    result = self.utility_handlers.handle_conflict_analysis_action(tool, query)
            
            if result is None:
                # CRITICAL SAFEGUARD: Double-check that list queries aren't routed to create
                query_lower = query.lower()
                is_list_query = any(phrase in query_lower for phrase in CALENDAR_QUESTION_PATTERNS)
                if is_list_query and action == "create":
                    logger.error(f"[CAL] CRITICAL BUG FIX: Final safeguard - list query '{query}' was about to execute create action - FORCING list")
                    action = "list"
                
                if action == "analyze_conflicts":
                    result = self.utility_handlers.handle_conflict_analysis_action(tool, query)
                elif action == "count":
                    result = self.list_search_handlers.handle_count_action(tool, query)
                elif action == "list":
                    result = self.list_search_handlers.handle_list_action(tool, query)
                elif action == "create":
                    result = self.event_handlers.handle_create_action(tool, query)
                elif action == "find_free_time":
                    result = self.utility_handlers.handle_find_free_time_action(tool, query)
                elif action == "search":
                    result = self.utility_handlers.handle_search_action(tool, query)
                elif action == "move":
                    result = self.event_handlers.handle_move_action(tool, query)
                elif action == "update":
                    result = self.event_handlers.handle_update_action(tool, query)
                elif action == "delete":
                    result = self.event_handlers.handle_delete_action(tool, query)
                elif "follow" in query.lower() and "up" in query.lower():
                    result = self.advanced_handlers.handle_followup_action(tool, query)
                elif "action" in query.lower() and "item" in query.lower():
                    # Check if query asks for meetings AND action items
                    # e.g., "What meetings do I have next week and what are the action items?"
                    query_lower = query.lower()
                    if any(phrase in query_lower for phrase in ["what meetings", "meetings do i", "meetings i have", "my meetings", "show meetings"]):
                        # This is a query asking for meetings AND their action items
                        # First list the meetings, then extract action items
                        result = self.advanced_handlers.handle_meetings_with_action_items(tool, query)
                    else:
                        # Regular action items extraction from a specific event
                        result = self.advanced_handlers.handle_extract_action_items_action(tool, query)
                elif "related" in query.lower() and "meeting" in query.lower():
                    result = self.advanced_handlers.handle_link_related_meetings_action(tool, query)
                elif "duplicate" in query.lower() or "duplicates" in query.lower():
                    result = self.utility_handlers.handle_find_duplicates_action(tool, query)
                elif "missing" in query.lower() and ("detail" in query.lower() or "description" in query.lower()):
                    result = self.utility_handlers.handle_find_missing_details_action(tool, query)
                elif "prepare" in query.lower() or "preparation" in query.lower():
                    result = self.advanced_handlers.handle_prepare_meeting_action(tool, query)
                elif "list" in query.lower() and "calendar" in query.lower():
                    result = self.utility_handlers.handle_list_calendars_action(tool, query)
                else:
                    # Default to listing events
                    result = tool._run(action="list")
            
            # Format response conversationally for calendar queries
            return self.format_response_conversationally(result, query)
                
        except Exception as e:
            logger.error(f"Calendar parsing failed: {e}", exc_info=True)
            error_msg = str(e)
            # Make error messages conversational
            if "not found" in error_msg.lower():
                return "I couldn't find what you're looking for. Could you provide more details?"
            elif "permission" in error_msg.lower():
                return "I don't have permission to do that. You might need to check your account settings."
            else:
                return f"I encountered an issue: {error_msg}. Could you try rephrasing your request?"
    
    def parse_query_to_params(self, query: str, user_id: Optional[int] = None, 
                              session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse calendar query and return structured parameters WITHOUT executing tools.
        
        This method replaces the old parse_query() approach by:
        1. Detecting the calendar action (list, create, update, delete, etc.)
        2. Extracting relevant entities (title, time, attendees, location, etc.)
        3. Calculating confidence score
        4. Providing metadata for debugging/suggestions
        
        Args:
            query: User's natural language query
            user_id: Optional user ID for personalization
            session_id: Optional session ID for context
            
        Returns:
            Dictionary with:
                - action: Calendar action type (list, create, update, delete, etc.)
                - entities: Extracted calendar entities (title, start_time, duration, attendees, location)
                - confidence: Float 0.0-1.0 indicating parsing confidence
                - metadata: Additional info (suggestions, warnings, etc.)
        """
        try:
            logger.info(f"[CAL] parse_query_to_params called with: '{query}'")
            
            learned_intent = self.learning_system.get_learned_intent(query)
            if learned_intent:
                logger.info(f"[CAL] Using learned intent: {learned_intent}")
            
            semantic_action = self.semantic_matcher.match_semantic(query, threshold=DEFAULT_SEMANTIC_THRESHOLD)
            
            is_schedule_query = any(phrase in query.lower() for phrase in [
                "schedule", "create", "book", "add to calendar", "new event", "new meeting"
            ])
            explicit_action = self.action_classifiers.detect_explicit_calendar_action(query.lower())
            
            # Override: Schedule queries should be 'create'
            if is_schedule_query and explicit_action and explicit_action != "create":
                logger.info(f"[CAL] Overriding {explicit_action} to 'create' for schedule query")
                explicit_action = "create"
            
            llm_intent = None
            llm_confidence = 0.0
            classification = None
            
            if self.classifier:
                try:
                    classification = self.action_classifiers.classify_calendar_query(query)
                    llm_confidence = classification.get('confidence', 0.5)
                    llm_intent = classification.get('intent', 'list')
                    logger.info(f"[CAL] LLM classification: {llm_intent} (confidence: {llm_confidence})")
                except Exception as e:
                    logger.warning(f"[CAL] LLM classification failed: {e}")
            
            action = self.action_classifiers.route_with_confidence(
                query=query,
                query_lower=query.lower(),
                llm_intent=llm_intent or learned_intent,
                llm_confidence=llm_confidence,
                semantic_action=semantic_action,
                explicit_action=explicit_action,
                is_schedule_query=is_schedule_query,
                classification=classification
            )
            
            logger.info(f"[CAL] Final routed action: {action}")
            
            entities = self._extract_entities_for_action(query, action, classification)
            
            confidence = self._calculate_confidence(query, action, entities, llm_confidence, classification)
            metadata = self._generate_metadata(query, action, entities, confidence, classification)
            
            return {
                'action': action,
                'entities': entities,
                'confidence': confidence,
                'metadata': metadata
            }
            
        except Exception as e:
            logger.error(f"[CAL] parse_query_to_params failed: {e}", exc_info=True)
            return {
                'action': 'list',  # Safe default
                'entities': {},
                'confidence': 0.3,
                'metadata': {
                    'error': str(e),
                    'suggestion': 'Falling back to list action due to parsing error'
                }
            }
    
    def _extract_entities_for_action(self, query: str, action: str, 
                                     classification: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract entities relevant to the detected action.
        
        Args:
            query: User query
            action: Detected action (list, create, update, etc.)
            classification: LLM classification result if available
            
        Returns:
            Dictionary of extracted entities
        """
        entities = {}
        
        # Common entities for all actions
        entities['title'] = self._extract_event_title(query)
        entities['has_time_reference'] = bool(re.search(
            r'\b(tomorrow|today|next week|this week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            query, re.IGNORECASE
        ))
        
        # Action-specific extraction
        if action == 'create':
            # Extract full event details
            # PRIORITY: Use intelligent title extraction first (creates better titles)
            entities['title'] = self._extract_event_title(query)
            entities['start_time'] = self._extract_event_time(query)
            entities['duration'] = self._extract_event_duration(query)
            entities['attendees'] = self._extract_attendees(query)
            entities['location'] = self._extract_location(query)
            
            # Use LLM classification as fallback/additional context if available
            if classification:
                llm_title = classification.get('event_title')
                # Only use LLM title if our intelligent extraction didn't find a good title
                if not entities.get('title') and llm_title:
                    entities['title'] = self._clean_event_title(llm_title)
                    logger.info(f"[CAL] Using LLM classification title as fallback: '{entities['title']}'")
                entities['llm_start_time'] = classification.get('start_time')
                entities['llm_end_time'] = classification.get('end_time')
                entities['llm_attendees'] = classification.get('attendees', [])
                entities['llm_location'] = classification.get('location')
        
        elif action == 'list':
            # Extract time range
            entities['start_time'] = self._extract_event_time(query)
            entities['time_period'] = self._extract_time_period(query)
            
            # Check for list modifiers
            query_lower = query.lower()
            entities['list_type'] = 'upcoming'  # Default
            if any(word in query_lower for word in ['tomorrow', "tomorrow's"]):
                entities['list_type'] = 'tomorrow'
            elif any(word in query_lower for word in ['today', "today's"]):
                entities['list_type'] = 'today'
            elif 'next week' in query_lower:
                entities['list_type'] = 'next_week'
            elif 'this week' in query_lower:
                entities['list_type'] = 'this_week'
        
        elif action == 'update':
            # Extract event identifier and new values
            entities['event_id'] = self._extract_event_reference(query)
            entities['new_title'] = self._extract_event_title(query)
            entities['new_start_time'] = self._extract_event_time(query)
            entities['new_location'] = self._extract_location(query)
        
        elif action == 'delete':
            # Extract event identifier
            entities['event_id'] = self._extract_event_reference(query)
        
        elif action == 'search':
            # Extract search term
            entities['search_term'] = self._extract_search_term(query)
        
        elif action == 'count':
            # Extract time period for counting
            entities['time_period'] = self._extract_time_period(query)
        
        elif action == 'analyze_conflicts':
            # Extract time range for conflict analysis
            entities['time_period'] = self._extract_time_period(query)
        
        return entities
    
    def _extract_time_period(self, query: str) -> Optional[str]:
        """Extract time period from query (e.g., 'today', 'this week', 'next month', 'yesterday', 'last week')."""
        query_lower = query.lower()
        
        # Past periods (check these first to avoid conflicts)
        if 'yesterday' in query_lower:
            return 'yesterday'
        elif 'last week' in query_lower or 'previous week' in query_lower:
            return 'last_week'
        elif 'last month' in query_lower or 'previous month' in query_lower:
            return 'last_month'
        elif 'before' in query_lower or 'past' in query_lower or 'ago' in query_lower:
            # Try to extract specific past period
            if 'week' in query_lower:
                return 'last_week'
            elif 'month' in query_lower:
                return 'last_month'
            else:
                # Default to yesterday for vague past queries
                return 'yesterday'
        
        # Future/current periods
        if 'tomorrow' in query_lower:
            return 'tomorrow'
        elif 'today' in query_lower:
            return 'today'
        elif 'next week' in query_lower:
            return 'next_week'
        elif 'this week' in query_lower:
            return 'this_week'
        elif 'next month' in query_lower:
            return 'next_month'
        elif 'this month' in query_lower:
            return 'this_month'
        
        # Specific dates with years: "January 15, 2027", "March 2025", "in 2027"
        # Check for year mentions (4-digit years)
        year_match = re.search(r'\b(19|20)\d{2}\b', query_lower)
        if year_match:
            year = int(year_match.group(0))
            # Check if it's a specific date with month/day
            month_day_year_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:,\s*|\s+)?(\d{4})', query_lower)
            if month_day_year_match:
                # Specific date with year - return as custom time_period
                return f"date_{year_match.group(0)}"
            # Just a year mention
            return f"year_{year}"
        
        # Generic extraction (handles "last week", "next week", etc.)
        match = re.search(r'(next|this|last|previous)\s+(week|month|year)', query_lower)
        if match:
            return f"{match.group(1)}_{match.group(2)}"
        
        return None
    
    def _extract_event_reference(self, query: str) -> Optional[str]:
        """Extract event ID or reference from query."""
        # Pattern 1: Event ID (numeric)
        match = re.search(r'event\s+(?:id\s+)?#?(\d+)', query, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Pattern 2: Event title reference
        match = re.search(r'(?:meeting|event|appointment)\s+["\']([^"\']+)["\']', query, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Pattern 3: Quoted reference
        match = re.search(r'["\']([^"\']+)["\']', query)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_search_term(self, query: str) -> Optional[str]:
        """Extract search term from query."""
        # Pattern 1: "search for X"
        match = re.search(r'search\s+(?:for\s+)?["\']?([^"\']+?)["\']?\s*(?:in|on|$)', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 2: "find X"
        match = re.search(r'find\s+["\']?([^"\']+?)["\']?\s*(?:in|on|$)', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 3: Quoted term
        match = re.search(r'["\']([^"\']+)["\']', query)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _calculate_confidence(self, query: str, action: str, entities: Dict[str, Any],
                             llm_confidence: float, classification: Optional[Dict[str, Any]]) -> float:
        """
        Calculate confidence score for the parsing result.
        
        Args:
            query: User query
            action: Detected action
            entities: Extracted entities
            llm_confidence: LLM classification confidence (if available)
            classification: Full LLM classification result
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Start with base confidence
        if llm_confidence > 0:
            base_confidence = llm_confidence
        else:
            base_confidence = 0.6  # Default for pattern-based parsing
        
        # Adjust based on entity extraction quality
        entity_bonus = 0.0
        
        if action == 'create':
            # High confidence if we have title and time
            if entities.get('title') and entities.get('start_time'):
                entity_bonus += 0.2
            elif entities.get('title') or entities.get('start_time'):
                entity_bonus += 0.1
            
            # Extra confidence for attendees or location
            if entities.get('attendees'):
                entity_bonus += 0.05
            if entities.get('location'):
                entity_bonus += 0.05
        
        elif action == 'list':
            # High confidence if we have time reference
            if entities.get('has_time_reference'):
                entity_bonus += 0.15
            if entities.get('time_period'):
                entity_bonus += 0.1
        
        elif action == 'search':
            # High confidence if we have search term
            if entities.get('search_term'):
                entity_bonus += 0.2
        
        elif action == 'update' or action == 'delete':
            # High confidence if we have event reference
            if entities.get('event_id'):
                entity_bonus += 0.2
        
        # Final confidence
        confidence = min(1.0, base_confidence + entity_bonus)
        
        logger.info(f"[CAL] Confidence: {confidence:.2f} (base: {base_confidence:.2f}, bonus: {entity_bonus:.2f})")
        
        return confidence
    
    def _generate_metadata(self, query: str, action: str, entities: Dict[str, Any],
                          confidence: float, classification: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate metadata for debugging and suggestions.
        
        Args:
            query: User query
            action: Detected action
            entities: Extracted entities
            confidence: Calculated confidence
            classification: LLM classification result
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'original_query': query,
            'parsed_at': datetime.now().isoformat(),
            'action_source': 'llm' if classification else 'pattern_based'
        }
        
        # Add suggestions for low confidence
        if confidence < 0.5:
            suggestions = []
            
            if action == 'create' and not entities.get('title'):
                suggestions.append('Consider providing an event title')
            if action == 'create' and not entities.get('start_time'):
                suggestions.append('Consider specifying when the event should be scheduled')
            if action == 'search' and not entities.get('search_term'):
                suggestions.append('Consider being more specific about what to search for')
            if action in ['update', 'delete'] and not entities.get('event_id'):
                suggestions.append('Consider specifying which event to modify')
            
            metadata['suggestions'] = suggestions
        
        # Add warnings for ambiguous queries
        if confidence < 0.7:
            metadata['warning'] = 'Low confidence - result may need verification'
        
        # Add LLM classification details if available
        if classification:
            metadata['llm_classification'] = {
                'intent': classification.get('intent'),
                'confidence': classification.get('confidence'),
                'reasoning': classification.get('reasoning', '')
            }
        
        return metadata

    # ==================== Entity Extraction Methods ====================
    
    def _extract_event_title(self, query: str) -> Optional[str]:
        """
        Extract event title from query using LLM-based semantic understanding.
        Creates concise, professional titles optimized for calendar events.
        
        Args:
            query: User query
            
        Returns:
            Event title or None if not found
        """
        # PRIORITY 1: Use LLM for intelligent title generation
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                import json
                
                prompt = f"""Create a concise, professional calendar event title from this query. 
The title should be clear, professional, and suitable for a calendar event.

Query: "{query}"

CRITICAL RULES:
1. Create a CONCISE title (preferably 3-8 words, max 60 characters)
2. Remove ALL action words: please, schedule, create, add, book, set up, make
3. Remove ALL date/time references: tomorrow, today, at 3:10, November 21, etc.
4. Remove filler words: "a", "the", "our", "my" when not essential
5. Use Title Case (capitalize important words)
6. Focus on the SUBJECT/TOPIC of the meeting, not the action

EXAMPLES:
- "Please book a meeting with Maniko tomorrow at 3:10 about our Clavr ideas" 
  → "Clavr Ideas Discussion" or "Clavr Meeting with Maniko"
  
- "Please schedule a 1:1 Clavr meeting tomorrow at 8 am" 
  → "1:1 Clavr Meeting"
  
- "Create a team standup for tomorrow" 
  → "Team Standup"
  
- "Schedule meeting with John tomorrow" 
  → "Meeting with John"
  
- "Add dentist appointment tomorrow" 
  → "Dentist Appointment"
  
- "Book a call with Sarah about the project next week"
  → "Project Call with Sarah"

GUIDELINES:
- If topic/subject is mentioned (e.g., "Clavr ideas"), prioritize it in the title
- If multiple people are mentioned, include them: "Meeting with John and Sarah"
- If it's a specific type of meeting (standup, 1:1, review), include that
- Keep it professional and calendar-appropriate
- Avoid redundant words like "meeting about" → just use the topic

Respond with ONLY valid JSON:
{{
    "title": "concise professional title",
    "confidence": 0.0-1.0
}}"""

                messages = [
                    SystemMessage(content="You are an expert at creating clear, professional calendar event titles."),
                    HumanMessage(content=prompt)
                ]
                
                response = self.llm_client.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Ensure response_text is a string
                if not isinstance(response_text, str):
                    response_text = str(response_text) if response_text else ""
                
                if response_text:
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        title = result.get('title', '').strip()
                        confidence = result.get('confidence', 0.7)
                        
                        if title and len(title) > 2 and confidence >= 0.7:
                            # Post-process: Clean up title
                            title = self._clean_event_title(title)
                            logger.info(f"[CAL] LLM extracted event title: '{title}' (confidence: {confidence})")
                            return title
            except Exception as e:
                logger.debug(f"[CAL] LLM title extraction failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based extraction
        query_lower = query.lower()
        
        # Pattern 1: "schedule/create/add [meeting/event] [title] [time/date]"
        # Match: "schedule a 1:1 Clavr meeting tomorrow at 8 am"
        # Extract: "1:1 Clavr meeting"
        match = re.search(r'(?:please\s+)?(?:schedule|create|add|book|set up|make)\s+(?:a\s+)?([^,]+?)\s+(?:meeting|event|appointment|call)\s+(?:tomorrow|today|at|on|for|next|this)', query, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Remove common action words that might have been captured
            title = re.sub(r'^\s*(please|schedule|create|add|book|set up|make)\s+', '', title, flags=re.IGNORECASE).strip()
            if title and len(title) > 2:
                return title
        
        # Pattern 2: "[title] meeting/event [time/date]"
        match = re.search(r'([^,]+?)\s+(?:meeting|event|appointment|call)\s+(?:tomorrow|today|at|on|for|next|this)', query, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Remove action words
            title = re.sub(r'^\s*(please|schedule|create|add|book|set up|make)\s+', '', title, flags=re.IGNORECASE).strip()
            if title and len(title) > 2:
                return title
        
        # Pattern 3: Quoted title
        match = re.search(r'["\']([^"\']+)["\']', query)
        if match:
            title = match.group(1).strip()
            return self._clean_event_title(title)
        
        return None
    
    def _clean_event_title(self, title: str) -> str:
        """
        Clean and format event title for professional calendar display.
        
        Args:
            title: Raw title string
            
        Returns:
            Cleaned, formatted title
        """
        if not title:
            return title
        
        # Remove leading/trailing whitespace
        title = title.strip()
        
        # Remove common action words if they appear at the start
        title = re.sub(r'^\s*(please|schedule|create|add|book|set up|make|schedule a|book a|create a)\s+', '', title, flags=re.IGNORECASE).strip()
        
        # Remove date/time references
        title = re.sub(r'\b(tomorrow|today|yesterday|next week|this week|last week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\b(at|on|for)\s+\d+[:\d]*\s*(am|pm|AM|PM)\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\b\d+[:\d]*\s*(am|pm|AM|PM)\b', '', title, flags=re.IGNORECASE)
        
        # Remove redundant "about" phrases
        title = re.sub(r'\s+about\s+', ' ', title, flags=re.IGNORECASE)
        
        # Remove extra whitespace
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Capitalize properly (Title Case)
        # Don't capitalize small words unless they're the first word
        small_words = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'if', 'in', 'of', 'on', 'or', 'the', 'to', 'with'}
        words = title.split()
        if words:
            words[0] = words[0].capitalize()
            for i in range(1, len(words)):
                if words[i].lower() not in small_words:
                    words[i] = words[i].capitalize()
                else:
                    words[i] = words[i].lower()
            title = ' '.join(words)
        
        return title
    
    def _extract_event_time(self, query: str) -> Optional[str]:
        """
        Extract event time from query using LLM-based semantic understanding
        
        Args:
            query: User query
            
        Returns:
            Time string or None if not found
        """
        # PRIORITY 1: Use LLM for semantic extraction (handles "tomorrow at 8 am" correctly)
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                import json
                
                prompt = f"""Extract the date and time from this query. Combine date and time expressions correctly.

Query: "{query}"

Examples:
- "tomorrow at 8 am" → "tomorrow at 8 am"
- "today at 3pm" → "today at 3pm"
- "next Monday at 2pm" → "next Monday at 2pm"
- "tomorrow" → "tomorrow"
- "at 8 am" → "at 8 am" (if no date specified, assume today)

CRITICAL:
- Combine date + time: "tomorrow at 8 am" should be extracted as "tomorrow at 8 am", not just "8 am"
- Preserve relative dates: tomorrow, today, next Monday, etc.
- Include time: 8 am, 3pm, 14:00, etc.

Respond with ONLY valid JSON:
{{
    "start_time": "the complete date and time expression",
    "confidence": 0.0-1.0
}}"""

                response = self.llm_client.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Ensure response_text is a string
                if not isinstance(response_text, str):
                    response_text = str(response_text) if response_text else ""
                
                if response_text:
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        start_time = result.get('start_time', '').strip()
                        confidence = result.get('confidence', 0.7)
                        
                        if start_time and len(start_time) > 1 and confidence >= 0.7:
                            logger.info(f"[CAL] LLM extracted event time: '{start_time}' (confidence: {confidence})")
                            return start_time
            except Exception as e:
                logger.debug(f"[CAL] LLM time extraction failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based extraction
        query_lower = query.lower()
        
        # Pattern 1: Combined date + time (e.g., "tomorrow at 8 am", "today at 3pm")
        match = re.search(r'\b(tomorrow|today|tonight|(?:next|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s+(?:at|@)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', query, re.IGNORECASE)
        if match:
            date_part = match.group(1).strip()
            time_part = match.group(2).strip()
            return f"{date_part} at {time_part}"
        
        # Pattern 2: Specific time (e.g., "at 3pm", "at 14:00")
        match = re.search(r'(?:at|@)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 3: Time with "on" (e.g., "on Monday at 3pm")
        match = re.search(r'(?:on|for)\s+(\w+)\s+(?:at|@)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', query, re.IGNORECASE)
        if match:
            return f"{match.group(1)} {match.group(2)}".strip()
        
        # Pattern 4: Relative time only (e.g., "tomorrow", "next Monday")
        match = re.search(r'\b(tomorrow|today|tonight|(?:next|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month))\b', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _extract_event_duration(self, query: str) -> Optional[int]:
        """
        Extract event duration from query in minutes
        
        Args:
            query: User query
            
        Returns:
            Duration in minutes or None if not found
        """
        # Pattern 1: "for X hours/minutes"
        match = re.search(r'for\s+(\d+)\s*(hour|hr|h|minute|min|m)s?', query, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            if unit.startswith('h'):
                return value * 60
            else:
                return value
        
        # Pattern 2: "X hour/minute meeting/event"
        match = re.search(r'(\d+)\s*(hour|hr|h|minute|min|m)s?\s+(?:meeting|event|appointment)', query, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            if unit.startswith('h'):
                return value * 60
            else:
                return value
        
        return None
    
    def _extract_attendees(self, query: str) -> List[str]:
        """
        Extract attendees/participants from query
        
        Args:
            query: User query
            
        Returns:
            List of attendee email addresses or names
        """
        attendees = []
        
        # Pattern 1: Email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        attendees.extend(re.findall(email_pattern, query))
        
        # Pattern 2: "with [name]" or "invite [name]"
        match = re.search(r'(?:with|invite)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', query)
        if match:
            name = match.group(1).strip()
            if name and name not in attendees:
                attendees.append(name)
        
        # Pattern 3: Multiple people "with X, Y, and Z"
        match = re.search(r'(?:with|invite)\s+((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*)?)+(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)?)', query)
        if match:
            names_str = match.group(1)
            # Split by commas and "and"
            names = re.split(r',\s*|\s+and\s+', names_str)
            for name in names:
                name = name.strip()
                if name and name not in attendees:
                    attendees.append(name)
        
        return attendees
    
    def _extract_location(self, query: str) -> Optional[str]:
        """
        Extract location from query
        
        Args:
            query: User query
            
        Returns:
            Location string or None if not found
        """
        # Pattern 1: "at [location]" (but not time patterns)
        match = re.search(r'(?:at|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:Room|Conference|Building|Office|Hall|Center)(?:\s+\w+)?)?)', query)
        if match:
            location = match.group(1).strip()
            # Avoid matching times like "at 3pm"
            if not re.match(r'\d', location):
                return location
        
        # Pattern 2: "location: X" or "venue: X"
        match = re.search(r'(?:location|venue|place|room):\s*([^\n,]+)', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 3: Quoted location
        match = re.search(r'(?:at|in)\s+["\']([^"\']+)["\']', query)
        if match:
            return match.group(1).strip()
        
        return None
    
    def extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract calendar-specific entities from query
        
        Args:
            query: User query
            
        Returns:
            Dictionary of extracted entities
        """
        entities = super().extract_entities(query)
        
        # Add calendar-specific entities
        entities.update({
            'title': self._extract_event_title(query),
            'start_time': self._extract_event_time(query),
            'duration': self._extract_event_duration(query),
            'attendees': self._extract_attendees(query),
            'location': self._extract_location(query),
            'action': self.action_classifiers.detect_calendar_action(query),
            'has_time_reference': bool(re.search(r'\b(tomorrow|today|next week|this week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', query, re.IGNORECASE))
        })
        
        return entities
    
    # ==================== Filter Methods ====================
    
    def _filter_events_to_today(self, result: str) -> str:
        """
        Filter events to only show today's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only today's events
        """
        if not result:
            return result
        
        today = datetime.now().date()
        return self._filter_events_by_date(result, today, today + timedelta(days=1))
    
    def _filter_events_to_tomorrow(self, result: str) -> str:
        """
        Filter events to only show tomorrow's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only tomorrow's events
        """
        if not result:
            return result
        
        tomorrow = datetime.now().date() + timedelta(days=1)
        return self._filter_events_by_date(result, tomorrow, tomorrow + timedelta(days=1))
    
    def _filter_events_to_yesterday(self, result: str) -> str:
        """
        Filter events to only show yesterday's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only yesterday's events
        """
        if not result:
            return result
        
        yesterday = datetime.now().date() - timedelta(days=1)
        return self._filter_events_by_date(result, yesterday, yesterday + timedelta(days=1))
    
    def _filter_events_to_next_week(self, result: str) -> str:
        """
        Filter events to only show next week's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only next week's events
        """
        if not result:
            return result
        
        today = datetime.now().date()
        # Next week starts 7 days from today
        next_week_start = today + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=7)
        return self._filter_events_by_date(result, next_week_start, next_week_end)
    
    def _filter_events_by_title(self, result: str, title: str) -> str:
        """
        Filter events by title.
        
        Args:
            result: Formatted event list result
            title: Title to filter by
            
        Returns:
            Filtered result with matching events
        """
        if not result or not title:
            return result
        
        title_lower = title.lower()
        lines = result.split('\n')
        filtered_lines = []
        current_event = []
        
        for line in lines:
            # Check if this line contains the title
            if title_lower in line.lower():
                if current_event:
                    filtered_lines.extend(current_event)
                    current_event = []
                filtered_lines.append(line)
            elif line.strip().startswith('**') or line.strip().startswith('*'):
                # Start of a new event
                if current_event:
                    current_event = []
                current_event.append(line)
            elif current_event:
                current_event.append(line)
        
        return '\n'.join(filtered_lines) if filtered_lines else result
    
    def _filter_events_by_date_range(self, result: str, start_date: datetime, end_date: datetime) -> str:
        """
        Filter events by date range.
        
        Args:
            result: Formatted event list result
            start_date: Start date for filtering
            end_date: End date for filtering
            
        Returns:
            Filtered result with events in date range
        """
        if not result:
            return result
        
        start_date_only = start_date.date() if isinstance(start_date, datetime) else start_date
        end_date_only = end_date.date() if isinstance(end_date, datetime) else end_date
        
        return self._filter_events_by_date(result, start_date_only, end_date_only)
    
    def _filter_events_by_date(self, result: str, start_date, end_date) -> str:
        """
        Internal helper to filter events by date range.
        
        Args:
            result: Formatted event list result
            start_date: Start date (date object)
            end_date: End date (date object)
            
        Returns:
            Filtered result
        """
        if not result:
            return result
        
        lines = result.split('\n')
        filtered_lines = []
        current_event = []
        include_event = False
        
        for line in lines:
            # Check if line contains a date
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\w+day,?\s+\w+\s+\d{1,2})', line)
            if date_match:
                # Try to parse the date
                try:
                    # Try ISO format first
                    if '-' in date_match.group(1):
                        event_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                    else:
                        # Try other formats
                        event_date = datetime.strptime(date_match.group(1), '%m/%d/%Y').date()
                    
                    if start_date <= event_date < end_date:
                        include_event = True
                        if current_event:
                            filtered_lines.extend(current_event)
                            current_event = []
                        filtered_lines.append(line)
                    else:
                        include_event = False
                        current_event = []
                except ValueError:
                    # Date parsing failed, include line if we're including current event
                    if include_event:
                        filtered_lines.append(line)
                    elif current_event:
                        current_event.append(line)
            elif include_event:
                filtered_lines.append(line)
            elif current_event:
                current_event.append(line)
        
        return '\n'.join(filtered_lines) if filtered_lines else result
    
    # ==================== Conversational Response Methods ====================
    
    def _generate_conversational_calendar_response(self, result: str, query: str, event_count: Optional[int] = None) -> Optional[str]:
        """
        Generate contextual, conversational response for calendar queries using LLM.
        
        Args:
            result: Raw tool result
            query: Original user query
            event_count: Optional event count for count queries
            
        Returns:
            Conversational response with contextual advice or None if generation fails
        """
        if not self.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            from datetime import datetime
            import pytz
            
            # Determine which prompt to use
            query_lower = query.lower()
            result_lower = result.lower() if result else ""
            
            # Gather context for LLM
            now = datetime.now(pytz.UTC)
            current_hour = now.hour
            is_late_night = current_hour >= 22
            is_early_morning = current_hour < 7
            
            # Extract event types from result
            event_types = []
            if result:
                reading_keywords = ['reading', 'read', 'book']
                fitness_keywords = ['workout', 'exercise', 'gym', 'run', 'fitness']
                meeting_keywords = ['meeting', 'call', 'standup', 'sync']
                
                result_lower_check = result.lower()
                if any(kw in result_lower_check for kw in reading_keywords):
                    event_types.append('reading')
                if any(kw in result_lower_check for kw in fitness_keywords):
                    event_types.append('fitness')
                if any(kw in result_lower_check for kw in meeting_keywords):
                    event_types.append('meeting')
            
            # Check if no events found
            is_no_results = (
                not result or 
                not result.strip() or 
                "no events" in result_lower or 
                "couldn't find" in result_lower or
                "don't see" in result_lower
            )
            
            if is_no_results:
                prompt = f"""You are Clavr, a friendly and encouraging personal assistant. Generate a natural, conversational response.

User asked: "{query}"
Context: No events found
Current hour: {current_hour}:00
Is late night: {is_late_night}
Is early morning: {is_early_morning}

Generate a friendly response that:
1. Confirms no events were found
2. Provides encouraging context (e.g., "You have a free schedule - great time to rest!" if late night)
3. Be warm and natural
4. Keep it concise (1-2 sentences)

Response:"""
            else:
                # Count events
                event_count_in_result = event_count if event_count is not None else (result.count('**') if result else 0)
                
                prompt = f"""You are Clavr, a friendly and encouraging personal assistant. Generate a natural, conversational response about calendar events.

User asked: "{query}"
Events found: {event_count_in_result}
Event types detected: {', '.join(event_types) if event_types else 'general'}
Current hour: {current_hour}:00
Is late night: {is_late_night}
Is early morning: {is_early_morning}

Events summary:
{result[:800]}

Generate a friendly response that:
1. Answers the query directly
2. Provides contextual, encouraging advice based on:
   - Event types (e.g., reading events → encourage reading habits)
   - Schedule density (many events → suggest balance/rest)
   - Time of day (late night → suggest sleep, early morning → encourage)
3. Be natural and warm, not robotic
4. Keep it concise (2-3 sentences max)
5. Only provide advice if genuinely helpful and relevant

Examples:
- Many events + late night → "You have {event_count_in_result} events scheduled. That's a busy schedule! Make sure to get enough rest tonight."
- Reading events → "Great to see reading on your calendar! Keep up the good habit."
- Early morning events → "Starting early - that's dedication! Have a productive day."

Response:"""

            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content.strip()
        except Exception as e:
            logger.debug(f"[CAL] Failed to generate conversational calendar response: {e}")
        
        return None
