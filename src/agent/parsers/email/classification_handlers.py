"""
Email Classification Handlers - Handle advanced query classification and routing

Integrates with:
- schemas.py: EmailClassificationSchema for structured intent classification
"""
import re
import json
import inspect
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger
from ....ai.prompts import (
    EMAIL_GENERIC_PROMPT,
    VALIDATION_PROMPT
)
from ....ai.prompts.utils import format_prompt
from .constants import EmailParserConfig

# Schema imports for type-safe classification
try:
    from ...schemas.schemas import EmailClassificationSchema
    HAS_SCHEMAS = True
except ImportError:
    HAS_SCHEMAS = False
    EmailClassificationSchema = Any

logger = setup_logger(__name__)


class EmailClassificationHandlers:
    """Handles email query classification, intent detection, and routing logic"""
    
    def __init__(self, email_parser):
        self.email_parser = email_parser
        self.llm_client = email_parser.llm_client
        self.learning_system = email_parser.learning_system
    
    def detect_email_action(self, query: str) -> str:
        """
        Detect the email action from the query 
        
        Args:
            query: User query
            
        Returns:
            Detected action
        """
        # CRITICAL: Validate query is not empty
        if not query or not query.strip():
            logger.warning(f"[EMAIL] detect_email_action called with empty query, defaulting to 'list'")
            return "list"
        
        # Extract actual query from conversation context first
        actual_query = self.email_parser.query_processing_handlers.extract_actual_query(query)
        
        # CRITICAL: Validate extracted query is not empty
        if not actual_query or not actual_query.strip():
            if query and query.strip():
                actual_query = query.strip()
                logger.debug(f"[EMAIL] extract_actual_query returned empty in detect_email_action, using original query")
            else:
                logger.warning(f"[EMAIL] Both extract_actual_query and original query are empty in detect_email_action, defaulting to 'list'")
                return "list"
        
        query_lower = actual_query.lower()
        
        logger.info(f"Detecting action for query: '{actual_query}'")
        
        # PRIORITY 0: Check for sender-specific queries (highest priority - must check before list)
        # If query contains "from [name]" or asks "what about", it's a search
        sender = self.email_parser.utility_handlers.extract_sender_from_query(actual_query)
        if sender:
            # Use LLM to detect if query is asking "what about" or "when"
            what_about_detection = self.detect_what_about_query(actual_query)
            asks_what_about = what_about_detection.get("asks_what_about", False)
            
            # Check for "when" queries using LLM classification if available
            # Otherwise use minimal pattern check as fallback
            asks_when = False
            if self.email_parser.classifier:
                try:
                    # Use classifier to detect temporal queries
                    # Note: inspect and asyncio are already imported at module level
                    classify_method = self.email_parser.classifier.classify_query
                    if inspect.iscoroutinefunction(classify_method):
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            classification = asyncio.run(classify_method(actual_query))
                            if classification and isinstance(classification, dict):
                                entities = classification.get('entities', {})
                                date_range = entities.get('date_range') if isinstance(entities, dict) else None
                                asks_when = "when" in query_lower or date_range is not None
                    else:
                        classification = classify_method(actual_query)
                        if classification and isinstance(classification, dict):
                            entities = classification.get('entities', {})
                            date_range = entities.get('date_range') if isinstance(entities, dict) else None
                            asks_when = "when" in query_lower or date_range is not None
                except Exception:
                    # Fallback: minimal pattern check
                    asks_when = "when" in query_lower or "last email from" in query_lower
            else:
                # Fallback: minimal pattern check
                asks_when = "when" in query_lower or "last email from" in query_lower
            
            # If asking "what about" or "when", route to search (which will handle summaries)
            if asks_what_about or asks_when:
                logger.info(f"[EMAIL] Detected search action for sender-specific query with 'what/when' question: '{sender}' (what_about: {asks_what_about}, when: {asks_when})")
                return "search"
            # If query has a sender but no time/content question, still search
            if "from" in query_lower:
                logger.info(f"[EMAIL] Detected search action for 'from {sender}' query")
                return "search"
        
        # PRIORITY 1: Urgency/priority email queries - treat as search with urgency prioritization
        # CRITICAL: These should be handled as search queries, not separate analysis action
        # The search will automatically prioritize urgent emails
        urgency_patterns = [
            "urgent matters", "urgent emails", "most urgent", "priority emails",
            "important emails", "priority email", "urgent email", "immediate attention",
            "emails that need", "emails requiring", "emails needing"
        ]
        # Only treat as urgency_analysis if it's asking for analysis/summary, not listing
        analysis_keywords = ["analysis", "summary", "what matters", "inbox analysis", "inbox summary", "email summary"]
        has_analysis_keyword = any(keyword in query_lower for keyword in analysis_keywords)
        
        if any(pattern in query_lower for pattern in urgency_patterns):
            # If asking for analysis/summary, use urgency_analysis
            # Otherwise, treat as search (which will prioritize urgent emails)
            if has_analysis_keyword:
                return "urgency_analysis"
            else:
                # Treat as search - will automatically prioritize urgent emails
                logger.info(f"[EMAIL] Priority/urgent email query detected - routing to search with urgency prioritization")
                return "search"
        
        # PRIORITY 2: Contact analysis patterns
        contact_patterns = [
            "who have i been emailing", "most contacts", "frequent contacts", 
            "top contacts", "contact analysis", "who do i email"
        ]
        if any(pattern in query_lower for pattern in contact_patterns):
            return "contact_analysis"
        
        # PRIORITY 3: Category analysis patterns
        if any(word in query_lower for word in ["categories", "dominate", "dominating", "category", "types", "kinds", "topics"]):
            return "category_analysis"
        
        # PRIORITY 4: Summarization patterns
        if any(word in query_lower for word in ["summarize", "summary", "key points", "brief summary"]):
            return "summarize"
        
        # PRIORITY 5: Email patterns and analytics
        if any(word in query_lower for word in ["response time", "email patterns", "email analytics", "email insights"]):
            return "email_patterns"
        
        # PRIORITY 6: Insights
        if any(word in query_lower for word in ["insights", "analytics", "patterns", "trends"]):
            return "insights"
        
        # PRIORITY 7: Semantic search
        if any(word in query_lower for word in ["semantic search", "search across folders", "find similar"]):
            return "semantic_search"
        
        # PRIORITY 8: Organize/Categorize
        if any(word in query_lower for word in ["organize", "categorize", "sort"]):
            return "organize"
        
        # PRIORITY 9: Archive operations
        if any(word in query_lower for word in ["archive", "move to archive"]):
            return "archive"
        
        # PRIORITY 10: Bulk operations
        if any(word in query_lower for word in ["bulk delete", "delete all", "bulk archive"]):
            return "bulk_delete"
        
        # PRIORITY: Use LLM-based classification FIRST for semantic understanding
        if self.email_parser.classifier:
            try:
                # CRITICAL: Use actual_query (extracted) not full query for classification
                # Handle async classify_query properly
                classify_method = self.email_parser.classifier.classify_query
                
                if inspect.iscoroutinefunction(classify_method):
                    # Handle async method - check if we're in an async context
                    try:
                        # Try to get the running event loop
                        loop = asyncio.get_running_loop()
                        # If we're in an async context, we can't use asyncio.run()
                        # Skip LLM classification in this case and use pattern-based fallback
                        logger.debug("[EMAIL] Skipping async classify_query in async context, using pattern-based detection")
                    except RuntimeError:
                        # No event loop running, safe to use asyncio.run()
                        try:
                            classification = asyncio.run(classify_method(actual_query))
                            # Ensure classification is a dict, not a list or other type
                            if isinstance(classification, list):
                                logger.warning(f"[EMAIL] LLM returned list instead of dict: {classification}, using fallback")
                                classification = None
                            elif classification and isinstance(classification, dict):
                                intent = classification.get('intent', 'list')
                                confidence = classification.get('confidence', 0.7)
                                logger.info(f"[EMAIL] LLM detected action: '{actual_query}' → {intent} (confidence: {confidence})")
                                
                                # Use LLM result if confidence is high enough
                                if confidence >= 0.7:
                                    # Map LLM intents to actions
                                    intent_to_action = {
                                        'search': 'search',
                                        'find': 'search',
                                        'list': 'list',
                                        'show': 'list',
                                        'display': 'list',
                                        'send': 'send',
                                        'write': 'send',
                                        'compose': 'send',
                                        'reply': 'reply',
                                        'respond': 'reply',
                                        'answer': 'reply',
                                        'unread': 'unread',
                                        'mark_read': 'mark_read',
                                        'mark_unread': 'mark_unread',
                                        'summarize': 'summarize',
                                        'summary': 'summarize',
                                        'archive': 'archive',
                                        'delete': 'delete'
                                    }
                                    
                                    action = intent_to_action.get(intent, 'list')
                                    logger.info(f"[EMAIL] Using LLM-detected action: {action}")
                                    return action
                        except Exception as inner_e:
                            logger.warning(f"[EMAIL] Error processing classification result: {inner_e}, using fallback")
                else:
                    # Sync version - call directly
                    try:
                        classification = classify_method(actual_query)
                        # Ensure classification is a dict, not a list or other type
                        if isinstance(classification, list):
                            logger.warning(f"[EMAIL] LLM returned list instead of dict: {classification}, using fallback")
                            classification = None
                        elif classification and isinstance(classification, dict):
                            intent = classification.get('intent', 'list')
                            confidence = classification.get('confidence', 0.7)
                            logger.info(f"[EMAIL] LLM detected action: '{actual_query}' → {intent} (confidence: {confidence})")
                            
                            # Use LLM result if confidence is high enough
                            if confidence >= 0.7:
                                # Map LLM intents to actions
                                intent_to_action = {
                                    'search': 'search',
                                    'find': 'search',
                                    'list': 'list',
                                    'show': 'list',
                                    'display': 'list',
                                    'send': 'send',
                                    'write': 'send',
                                    'compose': 'send',
                                    'reply': 'reply',
                                    'respond': 'reply',
                                    'answer': 'reply',
                                    'unread': 'unread',
                                    'mark_read': 'mark_read',
                                    'mark_unread': 'mark_unread',
                                    'summarize': 'summarize',
                                    'summary': 'summarize',
                                    'archive': 'archive',
                                    'delete': 'delete'
                                }
                                
                                action = intent_to_action.get(intent, 'list')
                                logger.info(f"[EMAIL] Using LLM-detected action: {action}")
                                return action
                    except Exception as inner_e:
                        logger.warning(f"[EMAIL] Error calling classify_method: {inner_e}, using fallback")
                
            except Exception as e:
                logger.warning(f"[EMAIL] LLM classification failed, using fallback: {e}")
        
        # Fallback to keyword detection
        if any(word in query_lower for word in ["search", "find", "look for"]):
            return "search"
        elif any(word in query_lower for word in ["send", "compose", "write"]):
            return "send"
        elif any(word in query_lower for word in ["reply", "respond"]):
            return "reply"
        elif "unread" in query_lower:
            return "unread"
        else:
            return "list"
    
    def detect_explicit_email_action(self, query_lower: str) -> Optional[str]:
        """
        Detect explicit email-specific action patterns before LLM classification.
        This helps avoid misclassification by the generic LLM classifier.
        """
        # Send/Compose patterns (highest priority for creation)
        if any(phrase in query_lower for phrase in [
            "send email", "send an email", "compose email", "write email",
            "draft email", "create email", "email to", "send to"
        ]):
            return "send"
        
        # Reply patterns
        if any(phrase in query_lower for phrase in [
            "reply to", "reply email", "respond to", "answer email"
        ]):
            return "reply"
        
        # List/Show patterns - MUST come before search patterns
        if any(phrase in query_lower for phrase in [
            "show emails", "list emails", "my emails", "recent emails",
            "check emails", "read emails", "what emails", "which emails",
            "emails do i have", "emails have i", "do i have emails",
            "any emails", "any new emails", "new emails", "emails today"
        ]):
            return "list"
        
        # Search patterns
        if any(phrase in query_lower for phrase in [
            "find emails", "search emails", "emails from", "emails about",
            "emails containing", "emails with", "look for emails"
        ]):
            return "search"
        
        # Summarize patterns
        if any(phrase in query_lower for phrase in [
            "summarize email", "email summary", "key points",
            "brief summary", "summarize emails"
        ]):
            return "summarize"
        
        # Unread patterns
        if any(phrase in query_lower for phrase in [
            "unread emails", "unread", "unread messages", "left unread",
            "oldest unread", "longest unread", "haven't read"
        ]):
            return "unread"
        
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
        Enhanced confidence-based routing for email intents with intelligent decision-making.
        
        Strategy:
        - High confidence (>0.85): Trust LLM, only override for critical misclassifications
        - Medium confidence (0.6-0.85): Use semantic + explicit patterns as tie-breaker
        - Low confidence (<0.6): Trust patterns more, LLM as fallback
        """
        # Map LLM intent to action
        intent_to_action = {
            'search': 'search',
            'find': 'search',
            'list': 'list',
            'show': 'list',
            'display': 'list',
            'send': 'send',
            'write': 'send',
            'compose': 'send',
            'reply': 'reply',
            'respond': 'reply',
            'answer': 'reply',
            'unread': 'unread',
            'mark_read': 'mark_read',
            'mark_unread': 'mark_unread',
            'summarize': 'summarize',
            'summary': 'summarize',
            'archive': 'archive'
        }
        
        llm_action = intent_to_action.get(llm_intent, 'list') if llm_intent else None
        
        # High confidence: Trust LLM
        if llm_confidence > EmailParserConfig.HIGH_CONFIDENCE_THRESHOLD:
            # Only override if explicit pattern strongly contradicts AND it's critical
            if explicit_action and explicit_action != llm_action:
                if self.is_critical_email_misclassification(query_lower, llm_action, explicit_action):
                    logger.warning(f"[ENHANCED] High confidence LLM ({llm_confidence}) overridden by critical pattern")
                    return explicit_action
            
            # Prefer semantic match if it agrees with LLM (validates LLM)
            if semantic_action == llm_action:
                logger.info(f"[ENHANCED] Semantic match validates LLM classification")
                return llm_action
            
            return llm_action or 'list'
        
        # Medium confidence: Use patterns as tie-breaker
        elif llm_confidence >= EmailParserConfig.DEFAULT_CONFIDENCE_THRESHOLD:
            # Prefer explicit pattern if it exists (more reliable)
            if explicit_action:
                logger.info(f"[ENHANCED] Medium confidence: using explicit pattern as tie-breaker")
                return explicit_action
            
            # Prefer semantic match if it exists
            if semantic_action:
                logger.info(f"[ENHANCED] Medium confidence: using semantic match")
                return semantic_action
            
            # Fall back to LLM
            return llm_action or 'list'
        
        # Low confidence: Trust patterns more
        else:
            # Explicit patterns have highest priority
            if explicit_action:
                logger.info(f"[ENHANCED] Low confidence: trusting explicit pattern")
                return explicit_action
            
            # Semantic patterns second
            if semantic_action:
                logger.info(f"[ENHANCED] Low confidence: trusting semantic pattern")
                return semantic_action
            
            # LLM as last resort
            return llm_action or 'list'
    
    def is_critical_email_misclassification(self, query_lower: str, llm_action: Optional[str], pattern_action: str) -> bool:
        """
        Check if this is a critical misclassification that must be corrected.
        
        Critical cases:
        - "show emails" → send (should be list)
        - "send email" → list (should be send)
        - "emails from X" → send (should be search)
        """
        critical_cases = [
            # List queries misclassified as send
            (['show emails', 'list emails', 'my emails', 'what emails'], 'send', 'list'),
            # Send queries misclassified as list
            (['send email', 'compose email', 'write email'], 'list', 'send'),
            # Search queries misclassified as send
            (['emails from', 'emails about', 'find emails'], 'send', 'search'),
            # Reply queries misclassified as send
            (['reply to', 'reply email', 'respond to'], 'send', 'reply'),
        ]
        
        for patterns, wrong_action, correct_action in critical_cases:
            if pattern_action == correct_action and llm_action == wrong_action:
                if any(pattern in query_lower for pattern in patterns):
                    logger.warning(f"[ENHANCED] Critical misclassification detected: {wrong_action} → {correct_action}")
                    return True
        
        return False
    
    def detect_what_about_query(self, query: str) -> Dict[str, Any]:
        """
        Use LLM to intelligently detect if a query is asking "what about" or requesting a summary.
        
        This replaces hardcoded pattern matching with semantic understanding.
        
        Args:
            query: User query
            
        Returns:
            Dict with:
                - asks_what_about: bool - Whether query asks what the email is about
                - asks_summary: bool - Whether query requests a summary
                - confidence: float - Confidence in detection
                - reasoning: str - Explanation of detection
        """
        if not self.llm_client:
            # Fallback: basic pattern check (minimal, only when LLM unavailable)
            query_lower = query.lower()
            asks_what_about = (
                ("what" in query_lower and "about" in query_lower) or
                ("what" in query_lower and "email" in query_lower and "about" in query_lower) or
                ("what" in query_lower and "say" in query_lower) or
                ("what" in query_lower and "did" in query_lower and "say" in query_lower)
            )
            return {
                "asks_what_about": asks_what_about,
                "asks_summary": asks_what_about,
                "confidence": 0.6 if asks_what_about else 0.4,
                "reasoning": "Pattern-based fallback (LLM unavailable)"
            }
        
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = f"""Analyze this email query and determine if the user is asking WHAT THE EMAIL IS ABOUT or requesting a SUMMARY.

Query: "{query}"

Understand that users may ask in various ways:
- "What is the email about?" / "What's the email about?"
- "What does the email say?" / "What did it say?"
- "What was the email about?" / "What was it about?"
- "Tell me about the email" / "Explain the email"
- "Summarize the email" / "Give me a summary"
- "What's in the email?" / "What does it contain?"
- "What email did I receive from X?" / "What email did X send?" → CRITICAL: This asks for CONTENT, not just listing
- "What email from X?" → CRITICAL: This asks for CONTENT, not just listing
- "What was the email I received yesterday from X all about?" → CRITICAL: This asks for CONTENT SUMMARY, not just listing
- "What did the email from X say?" → CRITICAL: This asks for CONTENT SUMMARY, not just listing

CRITICAL: Distinguish between:
- Asking WHAT an email is about (needs summary) → asks_what_about: true
- Asking IF emails exist (just listing) → asks_what_about: false
- Asking to summarize multiple emails → asks_summary: true
- Asking to list emails → asks_what_about: false
- Asking "What email did I receive from X?" → asks_what_about: true (user wants to know what it contains)
- Asking "What emails do I have?" → asks_what_about: false (just listing)
- Asking "What was the email from X all about?" → asks_what_about: true, asks_summary: true (user wants CONTENT SUMMARY)
- Asking "What did the email from X say?" → asks_what_about: true, asks_summary: true (user wants CONTENT SUMMARY)

Examples:
- "What is the email from John about?" → asks_what_about: true, asks_summary: true
- "What email did I receive from John?" → asks_what_about: true, asks_summary: true (user wants content)
- "What email did I receive from Alvaro yesterday?" → asks_what_about: true, asks_summary: true (user wants content)
- "What was the email I received yesterday from The Core all about?" → asks_what_about: true, asks_summary: true (user wants CONTENT SUMMARY)
- "What did the email from The Core say?" → asks_what_about: true, asks_summary: true (user wants CONTENT SUMMARY)
- "Do I have emails from John?" → asks_what_about: false, asks_summary: false
- "What emails do I have?" → asks_what_about: false, asks_summary: false
- "What did Sarah's email say?" → asks_what_about: true, asks_summary: true
- "Summarize emails from today" → asks_what_about: false, asks_summary: true

Respond with ONLY valid JSON:
{{
    "asks_what_about": true/false,
    "asks_summary": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation of why this is/isn't a what-about query"
}}"""

            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group(0))
                logger.info(f"[EMAIL] LLM detected 'what about' query: {result.get('asks_what_about')} (confidence: {result.get('confidence')})")
                return result
            else:
                logger.warning(f"[EMAIL] Failed to parse LLM response for 'what about' detection")
                return {
                    "asks_what_about": False,
                    "asks_summary": False,
                    "confidence": 0.0,
                    "reasoning": "Failed to parse LLM response"
                }
                
        except Exception as e:
            logger.warning(f"[EMAIL] LLM 'what about' detection failed: {e}, using fallback")
            # Fallback to basic pattern check
            query_lower = query.lower()
            asks_what_about = (
                ("what" in query_lower and "about" in query_lower) or
                ("what" in query_lower and "email" in query_lower and "about" in query_lower) or
                ("what" in query_lower and "say" in query_lower)
            )
            return {
                "asks_what_about": asks_what_about,
                "asks_summary": asks_what_about,
                "confidence": 0.5,
                "reasoning": f"Fallback pattern matching (LLM error: {str(e)})"
            }
    
    def detect_temporal_query(self, query: str) -> Dict[str, Any]:
        """
        Intelligently detect if query is asking about WHEN something happened (temporal query).
        Uses LLM-based detection to avoid hardcoded patterns.
        
        Args:
            query: User query
            
        Returns:
            Dict with:
                - asks_when: bool - Whether query asks when something happened
                - is_last_email_query: bool - Whether query asks about last email/interaction
                - confidence: float - Confidence in detection
                - reasoning: str - Explanation of detection
        """
        if not self.llm_client:
            # Minimal fallback only when LLM unavailable
            query_lower = query.lower()
            asks_when = "when" in query_lower
            is_last_email_query = "last" in query_lower and ("email" in query_lower or "respond" in query_lower or "reply" in query_lower)
            return {
                "asks_when": asks_when,
                "is_last_email_query": is_last_email_query,
                "confidence": 0.6 if asks_when else 0.4,
                "reasoning": "Pattern-based fallback (LLM unavailable)"
            }
        
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = f"""Analyze this email query and determine if the user is asking WHEN something happened (temporal query).

Query: "{query}"

Understand that users may ask temporal questions in various ways:
- "When was the last time X sent an email?"
- "When did X respond?" / "When did X reply?"
- "When was the last email from X?"
- "When did I last hear from X?"
- "When did X last email me?"
- "Last email from X" (implies temporal query)
- "When did X contact me?"

CRITICAL: Distinguish between:
- Asking WHEN something happened (temporal) → asks_when: true
- Asking WHAT something contains (content) → asks_when: false
- Asking about the LAST email/interaction → is_last_email_query: true
- Asking about any email → is_last_email_query: false

Examples:
- "When was the last time Alvaro sent an email?" → asks_when: true, is_last_email_query: true
- "When did Alvaro respond?" → asks_when: true, is_last_email_query: true
- "What email did I receive from Alvaro yesterday?" → asks_when: false, is_last_email_query: false (asks WHAT, not WHEN)
- "Last email from Alvaro" → asks_when: false, is_last_email_query: true (asks about last email, not when)
- "When did Sarah contact me?" → asks_when: true, is_last_email_query: false

Respond with ONLY valid JSON:
{{
    "asks_when": true/false,
    "is_last_email_query": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation of why this is/isn't a temporal query"
}}"""

            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group(0))
                logger.info(f"[EMAIL] LLM detected temporal query: asks_when={result.get('asks_when')}, is_last_email_query={result.get('is_last_email_query')} (confidence: {result.get('confidence')})")
                return result
            else:
                logger.warning(f"[EMAIL] Failed to parse LLM response for temporal query detection")
                return {
                    "asks_when": False,
                    "is_last_email_query": False,
                    "confidence": 0.0,
                    "reasoning": "Failed to parse LLM response"
                }
                
        except Exception as e:
            logger.warning(f"[EMAIL] LLM temporal query detection failed: {e}, using fallback")
            # Minimal fallback
            query_lower = query.lower()
            asks_when = "when" in query_lower
            is_last_email_query = "last" in query_lower and ("email" in query_lower or "respond" in query_lower or "reply" in query_lower)
            return {
                "asks_when": asks_when,
                "is_last_email_query": is_last_email_query,
                "confidence": 0.5,
                "reasoning": "Pattern-based fallback (LLM failed)"
            }
    
    def validate_classification(self, query: str, action: str, classification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Self-validation: LLM validates its own classification for email queries.
        
        Args:
            query: User query
            action: Proposed action
            classification: Original classification
            
        Returns:
            Validation result with should_correct flag and corrected_action if needed
        """
        if not self.llm_client:
            return {'should_correct': False, 'corrected_action': action}
        
        try:
            validation_prompt = format_prompt(
                VALIDATION_PROMPT,
                query=query,
                action=action,
                classification=json.dumps(classification, indent=2)
            )

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
                logger.info(f"[ENHANCED] Self-validation corrected: {action} → {corrected_action}")
                return {
                    'should_correct': True,
                    'corrected_action': corrected_action,
                    'reasoning': validation.get('reasoning', '')
                }
            
            return {'should_correct': False, 'corrected_action': action}
            
        except Exception as e:
            logger.warning(f"Self-validation failed: {e}")
            return {'should_correct': False, 'corrected_action': action}
    
    def classify_email_query_with_enhancements(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Enhanced email classification with few-shot learning and chain-of-thought reasoning.
        
        Args:
            query: User query
            
        Returns:
            Classification dict or None if classification fails
        """
        if not self.llm_client:
            return None
        
        # Try structured output with schema first if available
        if HAS_SCHEMAS and hasattr(self.llm_client, 'with_structured_output'):
            try:
                result = self.classify_with_schema(query)
                if result:
                    logger.info("[SCHEMA] Successfully classified with EmailClassificationSchema")
                    return result
            except Exception as e:
                logger.warning(f"[SCHEMA] Structured classification failed: {e}, falling back to JSON")
        
        # Fallback to JSON-based classification
        try:
            # Get similar successful queries for few-shot learning
            similar_examples = []
            if self.learning_system:
                similar_examples = self.learning_system.get_similar_successes(query, limit=3)
            
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
            
            # Build enhanced prompt with chain-of-thought reasoning
            prompt = f"""{EMAIL_GENERIC_PROMPT}

You are Clavr, an intelligent email assistant that understands natural language at any complexity level. Analyze this query and extract structured information.{examples_section}

Query: "{query}"

IMPORTANT: Understand complex email queries including:
- Sender-specific queries: "emails from John", "what did Sarah send"
- Time-based queries: "emails today", "recent emails", "last week's emails"
- Content-based queries: "emails about budget", "emails containing invoice"
- Action queries: "send email", "reply to", "forward email"
- Summary queries: "summarize emails", "key points from emails"

CRITICAL: Use chain-of-thought reasoning. Think through your classification step by step:

Step 1: What is the user trying to do?
- Are they asking to VIEW/SEE/LIST existing emails? → "list"
- Are they asking to SEARCH/FIND specific emails? → "search"
- Are they asking to SEND/COMPOSE a new email? → "send"
- Are they asking to REPLY/RESPOND to an email? → "reply"
- Are they asking to SUMMARIZE emails? → "summarize"
- Are they asking about UNREAD emails? → "unread"

Step 2: What keywords or phrases indicate this intent?
- List them: ...

Step 3: Are there any ambiguous parts?
- If yes, what are they? ...
- How should they be resolved? ...

Step 4: What is your confidence level?
- High (0.85-1.0): Very clear intent, no ambiguity
- Medium (0.6-0.85): Mostly clear, minor ambiguity
- Low (<0.6): Unclear, multiple interpretations possible

Step 5: Final classification
- Intent: ...
- Confidence: ...
- Reasoning: ...

Analyze and extract in JSON format:
1. intent: The action (options: list, search, send, reply, summarize, unread, mark_read, mark_unread, archive)
   - CRITICAL: Queries asking "show emails", "list emails", "my emails", "what emails", "emails do I have" are ALWAYS "list" intent, NOT "send"
   - CRITICAL: Queries asking "emails from X", "emails about Y", "find emails" are ALWAYS "search" intent, NOT "send"
   - CRITICAL: Queries asking "send email", "compose email", "write email" are ALWAYS "send" intent, NOT "list"
2. confidence: How certain you are (0.0-1.0) - be honest about uncertainty
3. reasoning: Brief explanation of your classification (1-2 sentences)
4. entities: Extract these entities:
   - sender: Email sender name or address
   - recipient: Email recipient name or address
   - subject: Email subject line
   - keywords: Search keywords or topics
   - date_range: Date/time expressions (e.g., "today", "yesterday", "this week")
   - folder: Email folder (e.g., "inbox", "sent", "archive")
5. filters: Any filters to apply (unread, important, attachment, etc.)
6. limit: Maximum number of results (default: 10)

Return ONLY valid JSON in this format:
{{
    "intent": "search",
    "confidence": 0.9,
    "reasoning": "User wants to find emails from a specific sender",
    "entities": {{
        "sender": "John Doe",
        "keywords": ["budget"],
        "date_range": "this week"
    }},
    "filters": ["unread"],
    "limit": 10
}}

Examples with reasoning:
- "Show me emails from John" → {{"intent": "search", "confidence": 0.95, "reasoning": "User wants to search for emails from a specific sender", "entities": {{"sender": "John"}}}}
- "What emails do I have?" → {{"intent": "list", "confidence": 0.95, "reasoning": "User wants to view/list existing emails", "filters": []}}
- "Send an email to Sarah about the meeting" → {{"intent": "send", "confidence": 0.95, "reasoning": "User explicitly wants to send/compose a new email", "entities": {{"recipient": "Sarah", "subject": "meeting"}}}}
- "Reply to the last email" → {{"intent": "reply", "confidence": 0.9, "reasoning": "User wants to reply to an existing email"}}
- "Summarize my emails from today" → {{"intent": "summarize", "confidence": 0.95, "reasoning": "User wants to summarize emails", "entities": {{"date_range": "today"}}}}

CRITICAL RULES:
1. Queries asking "what emails", "show emails", "list emails", "emails do I have" are ALWAYS "list" intent, NOT "send"
2. Only classify as "send" if the user explicitly asks to send, compose, write, or draft an email
3. Be honest about confidence - if uncertain, use lower confidence (0.6-0.7)
4. Always provide reasoning to explain your classification

If you cannot determine a field, use null, empty array [], or empty string "". Return ONLY the JSON, no explanations."""

            from langchain_core.messages import HumanMessage
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            # Try to extract JSON from response (in case LLM adds extra text)
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group(0)
            
            classification = json.loads(response_text)
            
            # Normalize classification to match QueryClassifier format
            return {
                'intent': classification.get('intent', 'list'),
                'confidence': classification.get('confidence', 0.5),
                'reasoning': classification.get('reasoning', ''),
                'entities': classification.get('entities', {}),
                'filters': classification.get('filters', []),
                'limit': classification.get('limit', EmailParserConfig.DEFAULT_EMAIL_LIMIT)
            }
            
        except Exception as e:
            logger.warning(f"Enhanced email classification failed: {e}")
            return None
    
    def classify_with_schema(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Classify email query using EmailClassificationSchema with structured outputs.
        
        This method uses the LLM's structured output capability to ensure
        type-safe, validated classification results.
        
        Args:
            query: User query
            
        Returns:
            Classification dict matching EmailClassificationSchema or None
        """
        if not self.llm_client or not HAS_SCHEMAS:
            return None
        
        try:
            prompt = f"""Classify this email query and extract structured information: "{query}"

Analyze the query and determine:
1. intent: The email action (search, send, summarize, list, analyze, delete, move, mark_read, mark_unread)
2. confidence: How certain you are (0.0-1.0)
3. entities: Extracted information like sender, recipient, subject, date_range, keywords, folder
4. filters: Filters to apply (unread, starred, important, has_attachments, etc.)
5. limit: Maximum number of results (default: 10)

CRITICAL RULES:
- "show emails", "list emails", "my emails" → intent: "list"
- "emails from X", "find emails", "search emails" → intent: "search"  
- "send email", "compose email" → intent: "send"
- "summarize emails" → intent: "summarize"

Examples:
- "Show me emails from John" → intent="search", entities={{"sender": "John"}}
- "What emails do I have?" → intent="list"
- "Send email to Sarah" → intent="send", entities={{"recipient": "Sarah"}}
"""
            
            # Use structured output
            structured_llm = self.llm_client.with_structured_output(EmailClassificationSchema)
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
            logger.warning(f"Schema-based classification failed: {e}")
            return None 
