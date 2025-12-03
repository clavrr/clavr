# filepath: /Users/maniko/Documents/notely-agent/src/agent/parsers/calendar/action_classifiers.py
"""
Calendar Action Classifier - Intelligent calendar query classification and routing

Integrates with:
- CalendarActionPatterns: Centralized pattern definitions
- CalendarActionClassifierConfig: Configuration and thresholds
- LLM: Advanced query classification with few-shot learning
- Learning system: Similar query examples for context

Features:
- Pattern-based detection (explicit calendar patterns)
- LLM-based classification (semantic understanding)
- Confidence-based routing (smart decision-making)
- Self-validation (error correction)
- Few-shot learning (context from similar queries)
"""

import json
import re
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ....utils.logger import setup_logger
from ...intent import CALENDAR_QUESTION_PATTERNS

# Import CALENDAR_CREATE_SYSTEM from tool_prompts
try:
    from ....ai.prompts.tool_prompts import CALENDAR_CREATE_SYSTEM
except ImportError:
    # Fallback if import fails
    CALENDAR_CREATE_SYSTEM = "You are a scheduling assistant. Create clear, complete calendar events."

logger = setup_logger(__name__)

# Centralized Calendar Classification Configuration
@dataclass
class CalendarActionPatterns:
    """Centralized patterns for calendar action detection"""
    
    # List/Query patterns - HIGHEST priority
    LIST_PATTERNS = [
        "what do i have", "what do i have on", "what's on", "whats on",
        "show me", "tell me about", "view my", "my calendar", "my schedule",
        "upcoming events", "upcoming meetings", "what meetings", "what events",
        "do i have anything", "have anything on", "have any meetings",
        "see my", "check my", "display my",
        "meetings do i have", "meetings have i", "my meetings", "which meetings",
        "calendar events do i have", "my calendar events", "which calendar events",
        "events do i have", "events have i", "my events", "which events"
    ]
    
    # Create/Schedule patterns
    CREATE_PATTERNS = [
        "create a", "create an", "book a", "book an",
        "add a", "add an", "add to calendar", "new event", "new meeting",
        "schedule a", "schedule an"
    ]
    
    # Delete/Cancel patterns
    DELETE_PATTERNS = [
        "delete", "remove", "cancel"
    ]
    
    # Update/Modify patterns
    UPDATE_PATTERNS = [
        "update", "modify", "change", "edit", "move", "reschedule", "shift"
    ]
    
    # Search patterns
    SEARCH_PATTERNS = [
        "search", "find", "look for"
    ]
    
    # Count patterns
    COUNT_PATTERNS = [
        "how many events", "how many calendar events", "how many meetings",
        "count events", "number of events", "number of calendar events",
        "total events", "total calendar events"
    ]
    
    # Conflict patterns
    CONFLICT_PATTERNS = [
        "conflict", "conflicts", "overlap", "overlapping", "double booking"
    ]


class CalendarActionClassifierConfig:
    """Centralized configuration for calendar action classification"""
    
    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    MEDIUM_CONFIDENCE_THRESHOLD = 0.6
    LOW_CONFIDENCE_THRESHOLD = 0.0
    
    # Intent to action mapping
    INTENT_TO_ACTION_MAP = {
        'create': 'create', 'schedule': 'create',
        'list': 'list', 'show': 'list', 'view': 'list', 'display': 'list',
        'search': 'search', 'find': 'search',
        'update': 'update', 'modify': 'update',
        'delete': 'delete', 'cancel': 'delete',
        'count': 'count',
        'analyze': 'analyze_conflicts'
    }
    
    # System prompt
    SYSTEM_PROMPT = "You are Clavr, an intelligent calendar assistant."
    
    # Validation settings
    MAX_RETRIES = 3
    ENABLE_SELF_VALIDATION = True
    ENABLE_FEW_SHOT_LEARNING = True
    
    @classmethod
    def get_patterns(cls) -> CalendarActionPatterns:
        """Get centralized patterns"""
        return CalendarActionPatterns()
    
    @classmethod
    def get_intent_to_action(cls, intent: str) -> str:
        """Map intent to action"""
        return cls.INTENT_TO_ACTION_MAP.get(intent.lower(), 'list')
    
    @classmethod
    def is_high_confidence(cls, confidence: float) -> bool:
        """Check if confidence is high"""
        return confidence > cls.HIGH_CONFIDENCE_THRESHOLD
    
    @classmethod
    def is_medium_confidence(cls, confidence: float) -> bool:
        """Check if confidence is medium"""
        return cls.MEDIUM_CONFIDENCE_THRESHOLD <= confidence <= cls.HIGH_CONFIDENCE_THRESHOLD
    
    @classmethod
    def is_low_confidence(cls, confidence: float) -> bool:
        """Check if confidence is low"""
        return confidence < cls.MEDIUM_CONFIDENCE_THRESHOLD


# Schema for structured outputs
try:
    from ...schemas.schemas import CalendarClassificationSchema
except ImportError:
    CalendarClassificationSchema = None


class CalendarActionClassifiers:
    """Handles calendar action classification and routing"""
    
    def __init__(self, parser):
        """
        Initialize action classifiers
        
        Args:
            parser: Parent CalendarParser instance
        """
        self.parser = parser
        self.llm_client = parser.llm_client
        self.learning_system = getattr(parser, 'learning_system', None)
        self.config = CalendarActionClassifierConfig()
        self.patterns = self.config.get_patterns()
    
    def detect_calendar_action(self, query: str) -> str:
        """
        Detect the calendar action from the query using pattern matching
        
        Uses centralized patterns from CalendarActionClassifierConfig for consistency
        
        Args:
            query: User query
            
        Returns:
            Detected action (create, list, search, update, delete, count, etc.)
        """
        query_lower = query.lower()
        
        # Count patterns (HIGHEST priority - for "how many events")
        if any(phrase in query_lower for phrase in self.patterns.COUNT_PATTERNS):
            return "count"
        
        # CRITICAL: Update patterns BEFORE create patterns to avoid misclassification
        # Patterns like "add a time to my event" should be update, not create
        update_patterns = [
            "add a time", "add time", "change time", "update time", "modify time",
            "add location", "change location", "update location", "modify location",
            "add attendees", "change attendees", "update attendees", "modify attendees",
            "add to event", "change my event", "update my event", "modify my event",
            "edit event", "edit my event", "change the event", "update the event"
        ]
        if any(phrase in query_lower for phrase in update_patterns):
            return "update"
        
        # Move/Reschedule patterns (also update-like, check before create)
        if any(word in query_lower for word in ["move", "reschedule", "shift"]):
            if any(phrase in query_lower for phrase in ["my ", "the ", "standup", "meeting", "event"]):
                return "move"
        
        # Update patterns (standard patterns)
        if any(word in query_lower for word in self.patterns.UPDATE_PATTERNS):
            return "update"
        
        # View/List patterns - MUST come before create patterns
        if any(phrase in query_lower for phrase in self.patterns.LIST_PATTERNS):
            return "list"
        
        # Conflict analysis patterns
        if any(word in query_lower for word in self.patterns.CONFLICT_PATTERNS) and \
           any(phrase in query_lower for phrase in ["check for", "analyze", "find", "detect", "are there"]):
            return "analyze_conflicts"
        
        # Find free time patterns
        if any(phrase in query_lower for phrase in [
            "find free time", "free time", "available time", "when am i free",
            "when am i available", "find a slot", "find time slot", "open time",
            "free slot", "available slot"
        ]):
            return "find_free_time"
        
        # Search patterns
        if any(word in query_lower for word in self.patterns.SEARCH_PATTERNS):
            return "search"
        
        # Create/Schedule patterns (check AFTER update patterns)
        if "schedule" in query_lower:
            return "create"
        if any(phrase in query_lower for phrase in self.patterns.CREATE_PATTERNS):
            return "create"
        
        # Delete patterns
        if any(word in query_lower for word in self.patterns.DELETE_PATTERNS):
            return "delete"
        
        return "list"
    
    def detect_explicit_calendar_action(self, query_lower: str) -> Optional[str]:
        """
        Detect explicit calendar-specific action patterns before LLM classification
        
        This helps avoid misclassification by the generic LLM classifier
        
        Args:
            query_lower: Lowercased query string
            
        Returns:
            Detected action or None
        """
        # Delete/Cancel patterns (check FIRST before anything else to prioritize)
        if any(word in query_lower for word in self.patterns.DELETE_PATTERNS):
            return "delete"
        
        # Count/Analyze patterns
        if any(phrase in query_lower for phrase in self.patterns.COUNT_PATTERNS):
            return "count"
        
        # Conflict analysis patterns
        if any(word in query_lower for word in self.patterns.CONFLICT_PATTERNS):
            return "analyze_conflicts"
        
        # View/List patterns - MUST come before create patterns
        if any(phrase in query_lower for phrase in self.patterns.LIST_PATTERNS):
            return "list"
        
        # Create patterns - only trigger if explicit creation words exist
        if any(phrase in query_lower for phrase in self.patterns.CREATE_PATTERNS):
            # Make sure it's about calendar/meeting
            calendar_indicators = ["event", "meeting", "appointment", "calendar", "schedule"]
            if any(indicator in query_lower for indicator in calendar_indicators):
                return "create"
            # Check for "schedule" or "book" pattern specifically
            if "schedule" in query_lower or "book" in query_lower:
                return "create"
        
        # Search patterns
        if any(phrase in query_lower for phrase in self.patterns.SEARCH_PATTERNS):
            return "search"
        
        # Update patterns
        if any(word in query_lower for word in self.patterns.UPDATE_PATTERNS):
            return "update"
        
        return None
    
    def route_with_confidence(
        self,
        query: str,
        query_lower: str,
        llm_intent: Optional[str],
        llm_confidence: float,
        semantic_action: Optional[str],
        explicit_action: Optional[str],
        is_schedule_query: bool,
        classification: Optional[Dict[str, Any]]
    ) -> str:
        """
        Enhanced confidence-based routing with intelligent decision-making.
        
        Uses centralized config thresholds for consistent confidence evaluation.
        
        Strategy:
        - High confidence (>0.85): Trust LLM, only override for critical misclassifications
        - Medium confidence (0.6-0.85): Use semantic + explicit patterns as tie-breaker
        - Low confidence (<0.6): Trust patterns more, LLM as fallback
        - Schedule queries: Prioritize "create" action if it's a schedule query
        """
        # CRITICAL: If this is a schedule query, prioritize "create" action
        if is_schedule_query:
            if explicit_action == "create" or semantic_action == "create" or (llm_intent and self.config.get_intent_to_action(llm_intent) == "create"):
                logger.info(f"[ENHANCED] Schedule query detected - prioritizing create action")
                return "create"
        
        # Map LLM intent to action using centralized config
        llm_action = self.config.get_intent_to_action(llm_intent) if llm_intent else None
        
        # High confidence: Trust LLM
        if self.config.is_high_confidence(llm_confidence):
            if explicit_action and explicit_action != llm_action:
                if self.is_critical_misclassification(query_lower, llm_action, explicit_action):
                    logger.warning(f"[ENHANCED] High confidence LLM ({llm_confidence}) overridden by critical pattern")
                    return explicit_action
            
            if semantic_action == llm_action:
                logger.info(f"[ENHANCED] Semantic match validates LLM classification")
                return llm_action
            
            return llm_action or 'list'
        
        # Medium confidence: Use patterns as tie-breaker
        elif self.config.is_medium_confidence(llm_confidence):
            if explicit_action:
                logger.info(f"[ENHANCED] Medium confidence: using explicit pattern as tie-breaker")
                return explicit_action
            
            if semantic_action:
                logger.info(f"[ENHANCED] Medium confidence: using semantic match")
                return semantic_action
            
            return llm_action or 'list'
        
        # Low confidence: Trust patterns more
        else:
            if explicit_action:
                logger.info(f"[ENHANCED] Low confidence: trusting explicit pattern")
                return explicit_action
            
            if semantic_action:
                logger.info(f"[ENHANCED] Low confidence: trusting semantic pattern")
                return semantic_action
            
            return llm_action or 'list'
    
    def is_critical_misclassification(self, query_lower: str, llm_action: Optional[str], pattern_action: str) -> bool:
        """Check if this is a critical misclassification that must be corrected"""
        critical_cases = [
            # List queries misclassified as create
            (['what meetings', 'meetings do i have', 'what events'], 'list', 'create'),
            # Create queries misclassified as list
            (['schedule', 'create', 'book'], 'create', 'list'),
        ]
        
        for patterns, correct_intent, wrong_intent in critical_cases:
            if any(p in query_lower for p in patterns):
                if llm_action == wrong_intent and pattern_action == correct_intent:
                    return True
        
        return False
    
    def validate_classification(self, query: str, action: str, classification: Dict[str, Any]) -> Dict[str, Any]:
        """Self-validation: Let LLM check its own classification using centralized config"""
        if not self.llm_client or not self.config.ENABLE_SELF_VALIDATION:
            return {'should_correct': False}
        
        prompt = f"""
        You classified this query as: {action} (confidence: {classification.get('confidence', 0.5)})
        
        Query: "{query}"
        
        Validate your classification:
        1. Is "{action}" the correct action for this query? (yes/no)
        2. If no, what should it be?
        3. Are you confident? (yes/no)
        
        Return JSON:
        {{
            "is_correct": true/false,
            "corrected_action": "list" or null,
            "confidence_ok": true/false
        }}
        """
        
        try:
            response = self.llm_client.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            if 'is_correct' in content.lower() and 'false' in content.lower():
                corrected = self.extract_corrected_action(content)
                if corrected and corrected != action:
                    return {
                        'should_correct': True,
                        'corrected_action': corrected
                    }
        except Exception as e:
            logger.warning(f"Self-validation failed: {e}")
        
        return {'should_correct': False}
    
    def extract_corrected_action(self, response_content: str) -> Optional[str]:
        """Extract corrected action from validation response"""
        content_lower = response_content.lower()
        for action in self.config.INTENT_TO_ACTION_MAP.values():
            if action in content_lower:
                return action
        return None
    
    def classify_calendar_query(self, query: str) -> Dict[str, Any]:
        """Classify calendar query using LLM"""
        if not self.llm_client:
            logger.warning("LLM not available for calendar classification")
            return self.basic_calendar_classify(query)
        
        prompt = self.build_calendar_classification_prompt(query)
        
        try:
            # Try structured outputs first
            classification = self.classify_calendar_with_structured_outputs(prompt)
            if classification:
                logger.info(f"[OK] Calendar query classified (structured): intent={classification.get('intent')}, "
                          f"confidence={classification.get('confidence')}")
                return classification
            
            # Fallback to prompt-based parsing
            response = self.llm_client.invoke(prompt)
            content = response.content
            
            # Clean the response
            content = content.strip()
            content = re.sub(r'```json\n?', '', content)
            content = re.sub(r'```\n?', '', content)
            content = re.sub(r'```', '', content)
            
            # Extract JSON object
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                json_str = json_match.group(0)
                try:
                    classification = json.loads(json_str)
                    logger.info(f"[OK] Calendar query classified: intent={classification.get('intent')}, "
                              f"confidence={classification.get('confidence')}")
                    return classification
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    logger.error(f"Content was: {content}")
            
            return self.basic_calendar_classify(query)
            
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return self.basic_calendar_classify(query)
    
    def classify_calendar_with_structured_outputs(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Classify calendar query using structured outputs for reliable classification"""
        if not self.llm_client:
            return None
        
        try:
            if hasattr(self.llm_client, 'with_structured_outputs'):
                try:
                    structured_llm = self.llm_client.with_structured_outputs(CalendarClassificationSchema)
                    
                    try:
                        response = structured_llm.invoke(prompt)
                    except (TypeError, AttributeError):
                        from langchain_core.messages import HumanMessage
                        messages = [HumanMessage(content=prompt)]
                        response = structured_llm.invoke(messages)
                    
                    # Extract classification from structured response
                    if isinstance(response, CalendarClassificationSchema):
                        classification = response.model_dump()
                    elif isinstance(response, dict):
                        classification = response
                    else:
                        classification = response.model_dump() if hasattr(response, 'model_dump') else {}
                    
                    if classification:
                        logger.info(f"[OK] Calendar classification using structured outputs")
                        return classification
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(f"Structured output calendar classification not available: {e}")
                    return None
        except Exception as e:
            logger.debug(f"Structured output calendar classification failed: {e}")
        
        return None
    
    def build_calendar_classification_prompt(self, query: str) -> str:
        """Build prompt for calendar LLM classification with few-shot examples"""
        # Get similar successful queries for few-shot learning
        similar_examples = []
        if self.learning_system:
            # Use default limit from learning system constants
            similar_examples = self.learning_system.get_similar_successes(query)
        
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
        
        # Use system prompt from templates as base
        return f"""{CALENDAR_CREATE_SYSTEM}

You are Clavr, an intelligent calendar assistant that understands natural language at any complexity level. Analyze this query and extract structured information.{examples_section}

Query: "{query}"

IMPORTANT: Understand complex calendar queries including:
- Relative time expressions: "in half an hour", "tomorrow evening", "between meetings"
- Constraints: "slow start", "after 5pm", "before lunch"
- Multi-step operations: "reorganize my day", "reschedule all calls"
- Context references: "my standup", "all calls today"

CRITICAL: Use chain-of-thought reasoning. Think through your classification step by step:

Step 1: What is the user trying to do?
- Are they asking to VIEW/SEE/LIST existing events? → "list"
- Are they asking to CREATE/SCHEDULE/BOOK a new event? → "create"
- Are they asking to MODIFY/UPDATE/CHANGE an event? → "update"
- Are they asking to DELETE/CANCEL/REMOVE an event? → "delete"
- Are they asking to SEARCH/FIND specific events? → "search"

Step 2: What keywords or phrases indicate this intent?
Step 3: Are there any ambiguous parts?
Step 4: What is your confidence level?
- High (0.85-1.0): Very clear intent, no ambiguity
- Medium (0.6-0.85): Mostly clear, minor ambiguity
- Low (<0.6): Unclear, multiple interpretations possible

Analyze and extract in JSON format:
1. intent: The action (options: list, create, schedule, search, update, delete, cancel, count, analyze, find_gap, reorganize)
   - CRITICAL: Queries asking "what meetings", "what events", "meetings do I have" are ALWAYS "list" intent, NOT "create"
2. confidence: How certain you are (0.0-1.0) - be honest about uncertainty
3. reasoning: Brief explanation of your classification (1-2 sentences)
4. entities: Extract these entities:
   - title: Event title or meeting name (CRITICAL: Remove action words like "please", "schedule", "create", "add", "book". Example: "Please schedule a 1:1 Clavr meeting" → "1:1 Clavr meeting")
   - start_time: When the event should start (CRITICAL: Combine date + time correctly. Example: "tomorrow at 8 am" → "tomorrow at 8 am", not just "8 am")
   - end_time: When the event should end (if specified)
   - duration: Duration in minutes or natural language
   - attendees: List of email addresses or names mentioned
   - location: Event location
   - description: Event description or details
   - date_range: Date/time expressions (e.g., "today", "tomorrow", "tomorrow evening")
   - constraints: Scheduling constraints ("between meetings", "slow start", "after 5pm", "before lunch")
   - relative_time: Relative time expressions ("in half an hour", "tomorrow evening")
5. filters: Any filters to apply (today, tomorrow, this week, etc.)

Return ONLY valid JSON in this format:
{{
    "intent": "create",
    "confidence": 0.9,
    "reasoning": "User wants to schedule a new event",
    "entities": {{"title": "Coffee Break", "duration": 30}},
    "filters": []
}}

CRITICAL RULES:
1. Queries asking "what meetings", "what events", "meetings do I have" are ALWAYS "list" intent, NOT "create"
2. Only classify as "create" if the user explicitly asks to schedule, create, book, or add an event
3. Be honest about confidence - if uncertain, use lower confidence (0.6-0.7)
4. Always provide reasoning to explain your classification

If you cannot determine a field, use null, empty array [], or empty string "". Return ONLY the JSON, no explanations."""
    
    def basic_calendar_classify(self, query: str) -> Dict[str, Any]:
        """Fallback basic classification using patterns"""
        query_lower = query.lower()
        
        intent = "list"
        confidence = 0.6
        
        if any(word in query_lower for word in ["create", "schedule", "book", "add"]):
            intent = "create"
            confidence = 0.7
        elif any(word in query_lower for word in ["search", "find", "look for"]):
            intent = "search"
            confidence = 0.7
        elif any(word in query_lower for word in ["delete", "remove", "cancel"]):
            intent = "delete"
            confidence = 0.7
        elif any(word in query_lower for word in ["update", "modify", "change", "move", "reschedule"]):
            intent = "update"
            confidence = 0.7
        
        return {
            "intent": intent,
            "confidence": confidence,
            "entities": {},
            "filters": []
        }
    
    def execute_calendar_with_classification(self, tool, query: str, classification: Dict[str, Any], action: str) -> str:
        """Execute calendar action with LLM classification"""
        try:
            # CRITICAL: Never route schedule/create queries to conflict analysis
            query_lower = query.lower()
            
            # CRITICAL SAFEGUARD: Check if this is a list/view query and force list action
            is_list_query = any(phrase in query_lower for phrase in CALENDAR_QUESTION_PATTERNS)
            
            if is_list_query and action == "create":
                logger.error(f"[CAL] CRITICAL BUG FIX: Query '{query}' is a list query but action was 'create' - FORCING list action")
                action = "list"
            
            if action == "analyze_conflicts":
                if any(phrase in query_lower for phrase in ["schedule", "create", "book", "add to calendar", "new event", "new meeting"]):
                    logger.warning(f"[CAL] BLOCKED: Query '{query}' contains schedule keywords - forcing create action")
                    action = "create"
            
            if action == "create":
                if is_list_query:
                    logger.error(f"[CAL] CRITICAL BUG FIX: Blocked create action for list query '{query}' - routing to list instead")
                    return self.parser.list_search_handlers.handle_list_action_with_classification(tool, query, classification)
                return self.parser.event_handlers.parse_and_create_calendar_event_with_llm(tool, query, classification)
            elif action == "list":
                return self.parser.list_search_handlers.handle_list_action_with_classification(tool, query, classification)
            elif action == "search":
                return self.parser.list_search_handlers.handle_search_action_with_classification(tool, query, classification)
            elif action == "count":
                return self.parser.list_search_handlers.handle_count_action_with_classification(tool, query, classification)
            elif action == "update":
                return self.parser.event_handlers.handle_update_action(tool, query)
            elif action == "delete":
                return self.parser.event_handlers.handle_delete_action(tool, query)
            elif action == "analyze_conflicts":
                return self.parser.utility_handlers.handle_conflict_analysis_action(tool, query)
            else:
                return self.parser.list_search_handlers.handle_list_action(tool, query)
        except Exception as e:
            logger.error(f"Calendar execution with classification failed: {e}")
            return self.parser.list_search_handlers.handle_list_action(tool, query)
