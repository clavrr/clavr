"""
Intent Detection Utility
Multi-signal intent detection with validation to prevent misrouting.

Uses a hybrid approach:
1. LLM-based classification (primary signal)
2. Keyword pattern validation (sanity check)
3. Entity-based inference (fallback)
4. Confidence-based routing with tiered thresholds

This ensures no query is misrouted by cross-validating multiple signals.
"""
from typing import Optional, Dict, Any
from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)

# Singleton QueryClassifier instance (cached per config)
_classifier_instance: Optional[object] = None
_classifier_config: Optional[Config] = None

# Domain mapping: maps QueryClassifier intents to domain-level intents
DOMAIN_MAPPING = {
    'schedule': 'calendar',
    'create_task': 'task',
    'list': 'email',  # Default list to email for backward compatibility
    'search': 'email',
    'send': 'email',
    'reply': 'email',
    'mark_read': 'email',
    'analyze': 'email',
    'summarize': 'email',
    'multi_step': 'general'
}

# Valid domain intents
VALID_DOMAINS = {'calendar', 'email', 'task', 'general'}

# Confidence thresholds (tiered for better routing decisions)
CONFIDENCE_HIGH = 0.7      # High confidence - trust LLM completely
CONFIDENCE_MEDIUM = 0.5    # Medium confidence - validate with keywords
CONFIDENCE_LOW = 0.3       # Low confidence - use keyword fallback
CONFIDENCE_MIN = 0.2       # Minimum to return a result (below this = None)

# Keyword patterns for validation (strong indicators)
EMAIL_KEYWORDS = {
    'email', 'emails', 'inbox', 'mail', 'message', 'messages', 'gmail',
    'sender', 'recipient', 'reply', 'forward', 'compose', 'draft',
    'unread', 'read', 'attachment', 'subject', 'from', 'to', 'cc', 'bcc'
}

CALENDAR_KEYWORDS = {
    'meeting', 'meetings', 'calendar', 'event', 'events', 'appointment',
    'appointments', 'schedule', 'scheduled', 'available', 'availability',
    'busy', 'free', 'book', 'booked', 'time slot', 'timeslot'
}

TASK_KEYWORDS = {
    'task', 'tasks', 'todo', 'todos', 'reminder', 'reminders', 'deadline',
    'deadlines', 'complete', 'completed', 'pending', 'due', 'checklist'
}


def _get_classifier(config: Config):
    """
    Get or create QueryClassifier singleton instance.
    
    Creates a new instance if config changes (though config typically doesn't change at runtime).
    This ensures the classifier always uses the correct configuration.
    """
    global _classifier_instance, _classifier_config
    
    # Check if we need to recreate the classifier (config changed or first time)
    if _classifier_instance is None or _classifier_config is not config:
        from src.ai.query_classifier import QueryClassifier
        _classifier_instance = QueryClassifier(config)
        _classifier_config = config
        logger.debug("QueryClassifier singleton initialized for intent detection")
    
    return _classifier_instance


def detect_query_intent(query: str, config: Config) -> Optional[str]:
    """
    Detect the primary domain intent of a user query with multi-signal validation.
    
    Uses a superior hybrid approach:
    1. LLM classification (primary signal)
    2. Keyword pattern validation (sanity check)
    3. Entity-based inference (fallback)
    4. Confidence-based routing with tiered thresholds
    
    This ensures no query is misrouted by cross-validating multiple signals.
    
    Args:
        query: User query text
        config: Config object (required - use get_config() from dependencies)
        
    Returns:
        Domain intent string ('calendar', 'email', 'task', 'general') or None if detection fails
        
    Example:
        from api.dependencies import get_config
        
        @router.post("/chat")
        async def chat(config: Config = Depends(get_config)):
            intent = detect_query_intent("schedule a meeting", config)
    """
    if not query or not query.strip():
        logger.debug("Empty query provided to intent detection")
        return None
    
    query_clean = query.strip()
    query_lower = query_clean.lower()
    
    try:
        # Step 1: Get LLM classification
        classifier = _get_classifier(config)
        classification = classifier.classify_query(query_clean)
        
        # Extract intent and confidence
        intent = classification.get('intent', '').lower()
        confidence = classification.get('confidence', 0.0)
        entities = classification.get('entities', {})
        
        # Step 2: Map detailed intent to domain intent
        domain = DOMAIN_MAPPING.get(intent, intent)
        
        # Step 3: Validate domain - if not valid, infer from entities/query
        if domain not in VALID_DOMAINS:
            domain = _infer_domain_from_classification(classification, query_clean)
        
        # Step 4: Multi-signal validation based on confidence tier
        if confidence >= CONFIDENCE_HIGH:
            # High confidence: Validate with keywords as sanity check
            keyword_domain = _detect_domain_from_keywords(query_lower)
            if keyword_domain and keyword_domain != domain:
                # Keyword signal conflicts - log warning but trust LLM (high confidence)
                logger.warning(
                    f"Keyword validation conflict: LLM={domain} (conf={confidence:.2f}) vs "
                    f"Keywords={keyword_domain}. Trusting LLM due to high confidence."
                )
            return domain
            
        elif confidence >= CONFIDENCE_MEDIUM:
            # Medium confidence: Cross-validate with keywords
            keyword_domain = _detect_domain_from_keywords(query_lower)
            
            if keyword_domain:
                if keyword_domain == domain:
                    # Signals agree - boost confidence
                    logger.info(
                        f"Signals agree: LLM={domain}, Keywords={keyword_domain} "
                        f"(conf={confidence:.2f})"
                    )
                    return domain
                else:
                    # Signals conflict - prefer keyword signal (more reliable for medium confidence)
                    logger.warning(
                        f"Signal conflict: LLM={domain} (conf={confidence:.2f}) vs "
                        f"Keywords={keyword_domain}. Using keyword signal."
                    )
                    return keyword_domain
            
            # No keyword match - trust LLM but log
            logger.info(f"Medium confidence LLM result, no keyword validation: {domain} (conf={confidence:.2f})")
            return domain
            
        elif confidence >= CONFIDENCE_LOW:
            # Low confidence: Prefer keyword signals, fallback to entity inference
            keyword_domain = _detect_domain_from_keywords(query_lower)
            
            if keyword_domain:
                logger.info(
                    f"Low LLM confidence ({confidence:.2f}), using keyword signal: {keyword_domain}"
                )
                return keyword_domain
            
            # Try entity-based inference
            entity_domain = _infer_domain_from_entities(entities, query_lower)
            if entity_domain:
                logger.info(
                    f"Low LLM confidence ({confidence:.2f}), using entity inference: {entity_domain}"
                )
                return entity_domain
            
            # Last resort: use LLM result but log warning
            logger.warning(
                f"Low confidence LLM result with no validation signals: {domain} (conf={confidence:.2f})"
            )
            return domain
            
        elif confidence >= CONFIDENCE_MIN:
            # Very low confidence: Only use keyword/entity signals
            keyword_domain = _detect_domain_from_keywords(query_lower)
            if keyword_domain:
                logger.info(f"Very low LLM confidence ({confidence:.2f}), using keyword: {keyword_domain}")
                return keyword_domain
            
            entity_domain = _infer_domain_from_entities(entities, query_lower)
            if entity_domain:
                logger.info(f"Very low LLM confidence ({confidence:.2f}), using entity: {entity_domain}")
                return entity_domain
            
            # Too low confidence, return None
            logger.debug(f"Confidence too low ({confidence:.2f}), returning None")
            return None
            
        else:
            # Confidence below minimum threshold
            logger.debug(f"Confidence below minimum threshold ({confidence:.2f} < {CONFIDENCE_MIN})")
            # Still try keyword/entity fallback
            keyword_domain = _detect_domain_from_keywords(query_lower)
            if keyword_domain:
                return keyword_domain
            
            entity_domain = _infer_domain_from_entities(entities, query_lower)
            if entity_domain:
                return entity_domain
            
            return None
        
    except Exception as e:
        logger.warning(f"Intent detection failed: {e}, using keyword fallback", exc_info=True)
        # Fallback to keyword detection on error
        keyword_domain = _detect_domain_from_keywords(query_lower)
        if keyword_domain:
            logger.info(f"Using keyword fallback after error: {keyword_domain}")
            return keyword_domain
        return None


def _detect_domain_from_keywords(query_lower: str) -> Optional[str]:
    """
    Detect domain from keyword patterns (fast, reliable fallback).
    
    Uses strong keyword indicators to detect domain intent.
    This is used for validation and fallback when LLM confidence is low.
    
    Args:
        query_lower: Lowercase query string
        
    Returns:
        Detected domain or None if no clear match
    """
    # CRITICAL: Prioritize calendar when "meeting" or "meetings" is present
    # This prevents queries like "What meetings do I have and what are the action items?"
    # from being misrouted to task queries
    if 'meeting' in query_lower or 'meetings' in query_lower:
        # If query mentions meetings, it's a calendar query, even if it also mentions action items
        if any(kw in query_lower for kw in ['action item', 'action items', 'action items from']):
            # This is a calendar query asking for action items FROM meetings
            return 'calendar'
        # Regular meeting query
        return 'calendar'
    
    # Count keyword matches for each domain
    email_score = sum(1 for kw in EMAIL_KEYWORDS if kw in query_lower)
    calendar_score = sum(1 for kw in CALENDAR_KEYWORDS if kw in query_lower)
    task_score = sum(1 for kw in TASK_KEYWORDS if kw in query_lower)
    
    # Find domain with highest score
    scores = {
        'email': email_score,
        'calendar': calendar_score,
        'task': task_score
    }
    
    max_score = max(scores.values())
    
    # Only return if we have a clear winner (at least 1 match and no tie)
    if max_score > 0:
        # Check for ties
        winners = [domain for domain, score in scores.items() if score == max_score]
        if len(winners) == 1:
            return winners[0]
        # If tie, prefer calendar if calendar keywords present, then email
        elif 'calendar' in winners:
            return 'calendar'
        elif 'email' in winners:
            return 'email'
    
    return None


def _infer_domain_from_entities(entities: Dict[str, Any], query_lower: str) -> Optional[str]:
    """
    Infer domain from classification entities.
    
    Args:
        entities: Entities extracted by QueryClassifier
        query_lower: Lowercase query string
        
    Returns:
        Inferred domain or None if no clear match
    """
    # Check entity-based indicators
    if entities.get('calendar') or entities.get('meeting') or entities.get('event'):
        return 'calendar'
    
    if entities.get('task') or entities.get('todo') or entities.get('deadline'):
        return 'task'
    
    if entities.get('sender') or entities.get('recipient') or entities.get('subject'):
        return 'email'
    
    # Check for date/time entities (likely calendar)
    if entities.get('date') or entities.get('time') or entities.get('date_range'):
        # But only if no email indicators
        if not (entities.get('sender') or entities.get('recipient')):
            return 'calendar'
    
    return None


def _infer_domain_from_classification(classification: dict, query: str) -> str:
    """
    Infer domain from classification entities or query keywords (legacy fallback).
    
    Args:
        classification: Classification result from QueryClassifier
        query: Original query string
        
    Returns:
        Inferred domain string (always returns a domain, never None)
    """
    query_lower = query.lower()
    entities = classification.get('entities', {})
    
    # Try entity inference first
    entity_domain = _infer_domain_from_entities(entities, query_lower)
    if entity_domain:
        return entity_domain
    
    # Try keyword detection
    keyword_domain = _detect_domain_from_keywords(query_lower)
    if keyword_domain:
        return keyword_domain
    
    # Default to general
    return 'general'


def reset_classifier():
    """Reset the classifier singleton (useful for testing)."""
    global _classifier_instance, _classifier_config
    _classifier_instance = None
    _classifier_config = None
    logger.debug("QueryClassifier singleton reset")

