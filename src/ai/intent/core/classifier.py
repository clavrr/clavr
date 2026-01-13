"""
Query Intent Classifier

Classifies queries into domains/intents based on patterns and keywords.
Uses pattern-first, LLM-second strategy for optimal speed.
"""
from typing import Dict, Any, Optional
from ..config.intent_constants import (
    EMAIL_PATTERNS, EMAIL_MANAGEMENT_PATTERNS,
    CALENDAR_PATTERNS, CALENDAR_QUESTION_PATTERNS,
    TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS, TASK_ANALYSIS_PATTERNS, TASK_QUESTION_PATTERNS,
    TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS
)
from ..config.classifier_config import (
    PATTERN_CONFIDENCE_THRESHOLD,
    get_fast_route,
)
from ...caching.intent_cache import global_intent_cache
from src.agents.constants import INTENT_KEYWORDS, DOMAIN_TOOL_ROUTING
from ..domain_detector import detect_domain


def classify_query_intent(query: str) -> Dict[str, Any]:
    """
    Classify query into domain and intent.
    
    Uses pattern-first, LLM-second strategy:
    1. Check cache
    2. Check fast paths (instant return)
    3. Try pattern matching (high confidence = skip LLM)
    4. Use LLM for ambiguous queries only
    
    Args:
        query: User query text
        
    Returns:
        Dict with domain, intent, confidence, routes_to
    """
    # 1. Check cache first
    cached = global_intent_cache.get_intent(query)
    if cached:
        return cached
    
    query_lower = query.lower().strip()
    
    # 2. Check fast paths (instant routing, no processing)
    fast_result = get_fast_route(query)
    if fast_result:
        global_intent_cache.set_intent(query, fast_result)
        return fast_result
    
    # 3. Try pattern-first approach using DomainDetector
    domain_result = detect_domain(query)
    
    if domain_result.confidence >= PATTERN_CONFIDENCE_THRESHOLD:
        # High confidence pattern match - skip LLM
        primary_domain = domain_result.primary_domain or "general"
        intent = _determine_intent(query_lower, primary_domain)
        routes_to = DOMAIN_TOOL_ROUTING.get(primary_domain, "supervisor")
        
        result = {
            "domain": primary_domain,
            "intent": intent,
            "confidence": "high" if domain_result.confidence >= 0.9 else "medium",
            "routes_to": routes_to,
            "score": int(domain_result.confidence * 10),
            "pattern_matched": True
        }
        global_intent_cache.set_intent(query, result)
        return result
    
    # 4. Use LLM only for ambiguous queries (low pattern confidence)
    try:
        from .llm_analyzer import get_llm_analyzer
        analyzer = get_llm_analyzer()  # Singleton - no instantiation overhead
        analysis = analyzer.analyze(query)
        
        # Map LLM output to existing structure
        primary_domain = analysis.get('domain', 'general')
        intent = analysis.get('intent', 'general')
        llm_confidence = analysis.get('confidence', 0.5)
        
        if llm_confidence >= 0.8:
            confidence = "high"
        elif llm_confidence >= 0.5:
            confidence = "medium"
        else:
            confidence = "low"
            
        # If LLM returns 'general' or low confidence, fall back to patterns
        if primary_domain == 'general' or confidence == 'low':
            raise ValueError("LLM returned general/low confidence")
              
        routes_to = DOMAIN_TOOL_ROUTING.get(primary_domain, "supervisor")
        
        result = {
            "domain": primary_domain,
            "intent": intent,
            "confidence": confidence,
            "routes_to": routes_to,
            "score": 10 if confidence == "high" else 5,
            "analysis": analysis
        }
        
        global_intent_cache.set_intent(query, result)
        return result
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"LLM fallback to patterns: {e}")
    
    # 5. Final fallback: pattern matching with lower threshold
    return _fallback_pattern_match(query, query_lower)
def _fallback_pattern_match(query: str, query_lower: str) -> Dict[str, Any]:
    """Fallback pattern matching when LLM fails or returns low confidence."""
    scores = {domain: 0 for domain in INTENT_KEYWORDS.keys()}
    scores["general"] = 0
    
    # Calculate scores based on keywords
    for domain, categories in INTENT_KEYWORDS.items():
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in query_lower:
                    scores[domain] += 1
    
    # Find primary domain
    primary_domain = "general"
    max_score = 0
    
    for domain, score in scores.items():
        if score > max_score:
            max_score = score
            primary_domain = domain
    
    # Determine confidence
    if max_score >= 2:
        confidence = "medium"
    elif max_score >= 1:
        confidence = "low"
    else:
        confidence = "low"
        primary_domain = "general"
    
    intent = _determine_intent(query_lower, primary_domain)
    routes_to = DOMAIN_TOOL_ROUTING.get(primary_domain, "supervisor")
    
    result = {
        "domain": primary_domain,
        "intent": intent,
        "confidence": confidence,
        "routes_to": routes_to,
        "score": max_score
    }
    
    global_intent_cache.set_intent(query, result)
    return result


def _determine_intent(query_lower: str, domain: str) -> str:
    """Determine specific intent within a domain using standard keywords."""
    
    if domain in INTENT_KEYWORDS:
        for intent_name, keywords in INTENT_KEYWORDS[domain].items():
            if any(k in query_lower for k in keywords):
                return intent_name
                
    # Generic fallbacks
    if any(word in query_lower for word in ["create", "add", "new", "schedule", "make"]):
        return "create"
    if any(word in query_lower for word in ["find", "search", "show", "get", "list", "read"]):
        return "search"
    
    return "general"
