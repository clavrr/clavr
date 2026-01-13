"""
Intent Analyzer

Implements query complexity analysis and entity extraction.
Uses DomainDetector for unified domain detection.
"""
from typing import Dict, List, Any
from ..config.intent_constants import (
    MULTI_STEP_PATTERNS, ACTION_VERBS,
)
from ...caching.intent_cache import global_intent_cache
from ..domain_detector import detect_domain

def analyze_query_complexity(query: str) -> Dict[str, Any]:
    """
    Analyze query complexity and characteristics
    
    Returns:
        Dict with complexity metrics and routing recommendations
    """
    # Check cache
    cached = global_intent_cache.get_complexity(query)
    if cached:
        return cached

    # Use LLM Analyzer for deeper understanding (singleton)
    try:
        from .llm_analyzer import get_llm_analyzer
        analyzer = get_llm_analyzer()
        analysis = analyzer.analyze(query)
        
        # Extract metadata from LLM analysis
        domain = analysis.get('domain', 'general')
        entities = analysis.get('entities', {})
        
        # Calculate complexity based on extracted entities
        # More entities generally means more complex
        entity_count = len(entities.get('time_references', [])) + \
                      len(entities.get('people', [])) + \
                      len(entities.get('priorities', []))
        
        multi_step = 1 if entity_count > 2 else 0
        domains = [domain] if domain != 'general' else []
        
        complexity_score = entity_count * 1.5 + (2 if domain != 'general' else 0)
        
        if complexity_score >= 4:
            complexity_level = "high"
            recommended_execution = "orchestrated"
        elif complexity_score >= 2:
            complexity_level = "medium" 
            recommended_execution = "orchestrated"
        else:
            complexity_level = "low"
            recommended_execution = "standard"
            
        result = {
            "complexity_score": complexity_score,
            "complexity_level": complexity_level,
            "multi_step_indicators": multi_step,
            "action_verbs_detected": 1 if analysis.get('intent') != 'general' else 0,
            "domains_detected": domains,
            "cross_domain": False, # LLM currently returns single domain
            "recommended_execution": recommended_execution,
            "should_use_orchestration": complexity_score >= 2,
            "analysis": analysis
        }
        
        global_intent_cache.set_complexity(query, result)
        return result
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM Analyzer failed in complexity analysis: {e}")
        # Fallback to legacy logic
        pass

    query_lower = query.lower()
    
    # Multi-step indicators
    multi_step_count = sum(1 for pattern in MULTI_STEP_PATTERNS if pattern in query_lower)
    action_verb_count = sum(1 for verb in ACTION_VERBS if verb in query_lower)
    
    # Domain detection - use centralized DomainDetector
    domain_result = detect_domain(query)
    domains = domain_result.domains
    
    # Complexity scoring
    complexity_score = 0
    complexity_score += multi_step_count * 2
    complexity_score += action_verb_count * 1
    complexity_score += len(domains) * 1
    
    # Determine complexity level
    if complexity_score >= 4:
        complexity_level = "high"
        recommended_execution = "orchestrated"
    elif complexity_score >= 2:
        complexity_level = "medium" 
        recommended_execution = "orchestrated"
    else:
        complexity_level = "low"
        recommended_execution = "standard"
    
    result = {
        "complexity_score": complexity_score,
        "complexity_level": complexity_level,
        "multi_step_indicators": multi_step_count,
        "action_verbs_detected": action_verb_count,
        "domains_detected": domains,
        "cross_domain": len(domains) > 1,
        "recommended_execution": recommended_execution,
        "should_use_orchestration": complexity_score >= 2
    }
    
    # Cache result
    global_intent_cache.set_complexity(query, result)
    return result

def extract_entities(query: str) -> Dict[str, List[str]]:
    """
    Extract entities from query for better processing.
    Uses LLM Analyzer for superior entity extraction.
    
    Returns:
        Dict with extracted entities by type
    """
    # Check cache
    cached = global_intent_cache.get_entities(query)
    if cached:
        return cached

    # Use LLM Analyzer (singleton)
    try:
        from .llm_analyzer import get_llm_analyzer
        analyzer = get_llm_analyzer()
        analysis = analyzer.analyze(query)
        
        entities = analysis.get('entities', {})
        
        # Normalize to expected format
        result = {
            "time_references": entities.get('time_references', []),
            "priorities": entities.get('priorities', []),
            "actions": [analysis.get('intent')] if analysis.get('intent') != 'general' else [],
            "people": entities.get('people', []),
            "domains": [analysis.get('domain')] if analysis.get('domain') != 'general' else []
        }
        
        global_intent_cache.set_entities(query, result)
        return result
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM Analyzer failed in entity extraction: {e}")
        # Fallback will logic below
        pass

    # Use QueryExtractor if available
    except Exception as e:
        # Log and fall back to manual extraction
        import logging
        logging.getLogger(__name__).debug(f"LLM entity extraction failed: {e}")
    
    # Fallback to manual extraction
    query_lower = query.lower()
    entities = {
        "time_references": [],
        "priorities": [],
        "actions": [],
        "domains": []
    }
    
    # Time references
    time_words = ["today", "tomorrow", "next week", "this week", "overdue", "urgent", "deadline"]
    entities["time_references"] = [word for word in time_words if word in query_lower]
    
    # Priority indicators
    priority_words = ["urgent", "important", "priority", "critical", "asap"]
    entities["priorities"] = [word for word in priority_words if word in query_lower]
    
    # Actions
    entities["actions"] = [verb for verb in ACTION_VERBS if verb in query_lower]
    
    # Domains - use centralized DomainDetector
    domain_result = detect_domain(query)
    entities["domains"] = domain_result.domains
    
    # Cache result
    global_intent_cache.set_entities(query, entities)
    return entities

