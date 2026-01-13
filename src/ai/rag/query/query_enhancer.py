"""
Query Enhancement Module

Improves RAG accuracy by enhancing queries before retrieval.
Includes query expansion, reformulation, and intent understanding.
"""
import re
from typing import List, Dict, Any, Optional
import spacy
import dateparser
from ....utils.logger import setup_logger
from ..utils.utils import extract_keywords

from .rules import (
    SYNONYMS, TEMPORAL_PATTERNS, COMMON_ENTITY_STOPWORDS, 
    URGENCY_SUBJECT_PATTERNS, IMPORTANCE_CONTENT_KEYWORDS
)

logger = setup_logger(__name__)


class QueryEnhancer:
    """
    Enhances queries for better RAG retrieval accuracy.
    
    Features:
    - Query expansion with synonyms
    - Intent understanding
    - Query reformulation
    - Entity extraction (spaCy NER)
    - Temporal understanding (dateparser)
    """
    
    def __init__(self, use_llm_expansion: bool = False, llm_client: Optional[Any] = None):
        """
        Initialize query enhancer.
        
        Args:
            use_llm_expansion: Use LLM for query expansion
            llm_client: Optional LLM client
        """
        self.use_llm_expansion = use_llm_expansion
        self.llm_client = llm_client
        self.nlp = None
        # Initialize synonyms from rules, allowing instance-level customization
        self.synonyms = SYNONYMS.copy()
    
    def load_custom_synonyms(self, path: str):
        """Load custom synonyms from a JSON or YAML file."""
        import json
        import yaml
        import os
        
        if not os.path.exists(path):
            logger.warning(f"Synonym file not found: {path}")
            return
            
        try:
            with open(path, 'r') as f:
                if path.endswith('.json'):
                    custom = json.load(f)
                elif path.endswith('.yaml') or path.endswith('.yml'):
                    custom = yaml.safe_load(f)
                else:
                    logger.warning("Unsupported synonym file format. Use .json or .yaml")
                    return
            
            if isinstance(custom, dict):
                # Update/Merge synonyms
                for term, synonyms in custom.items():
                    if term in self.synonyms:
                        # Append new unique synonyms
                        current = set(self.synonyms[term])
                        current.update(synonyms)
                        self.synonyms[term] = list(current)
                    else:
                        self.synonyms[term] = synonyms
                logger.info(f"Loaded custom synonyms from {path}")
        except Exception as e:
            logger.error(f"Failed to load synonyms: {e}")

    def _load_spacy_if_needed(self):
        """Lazy load spaCy model."""
        if self.nlp is None:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning("spaCy model 'en_core_web_sm' not found. Downloads taking place? Run: python -m spacy download en_core_web_sm")
                # Fallback to blank if model missing
                self.nlp = spacy.blank("en")

    async def enhance(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance a query for better retrieval (Async).
        
        Args:
            query: Original query
            context: Optional context (e.g., user preferences, recent queries)
            
        Returns:
            Enhanced query dictionary
        """
        # Ensure spaCy is loaded
        self._load_spacy_if_needed()
        
        original = query.strip()
        
        # Extract intent
        intent = self._detect_intent(original)
        
        # Extract entities
        entities = self._extract_entities(original)
        
        # Extract temporal constraints
        temporal = self._extract_temporal(original)
        
        # Expand query with synonyms
        expanded = self._expand_query(original)
        
        # Generate query variants
        reformulated = self._reformulate_query(original, intent, entities)
        
        # LLM-based expansion if enabled
        if self.use_llm_expansion and self.llm_client:
            try:
                llm_expanded = await self._llm_expand_query(original, intent, context)
                if llm_expanded:
                    expanded = f"{expanded} {llm_expanded}".strip()
            except Exception as e:
                logger.debug(f"LLM expansion failed: {e}")
        
        result = {
            'original': original,
            'expanded': expanded,
            'reformulated': reformulated,
            'intent': intent,
            'entities': entities,
            'temporal': temporal,
            'keywords': extract_keywords(expanded)
        }
        
        if isinstance(temporal, dict):
             result['temporal_metadata'] = temporal
             
        return result

    def enhance_sync(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Synchronous wrapper for enhance."""
        self._load_spacy_if_needed()
        
        original = query.strip()
        intent = self._detect_intent(original)
        entities = self._extract_entities(original)
        temporal = self._extract_temporal(original)
        expanded = self._expand_query(original)
        reformulated = self._reformulate_query(original, intent, entities)
        
        result = {
            'original': original,
            'expanded': expanded,
            'reformulated': reformulated,
            'intent': intent,
            'entities': entities,
            'temporal': temporal,
            'keywords': extract_keywords(expanded)
        }
        
        if isinstance(temporal, dict):
             result['temporal_metadata'] = temporal
        
        return result
    
    @staticmethod
    def detect_intent(query: str) -> str:
        # ... (intent detection logic unchanged for now) ...
        return QueryEnhancer._detect_intent_static(query)

    @staticmethod
    def _detect_intent_static(query: str) -> str:
        """Isolated intent detection logic."""
        query_lower = query.lower()
        
        # Financial/spending queries
        if any(term in query_lower for term in ['spend', 'spent', 'cost', 'paid', 'payment', 'receipt', 
                                                'invoice', 'total', 'amount', 'how much', 'expense', 'expenses']):
            return 'financial'
            
        # Action queries (from AdaptiveRerankingWeights)
        action_keywords = ['send', 'sent', 'reply', 'forward', 'delete', 'archive', 'move', 'mark']
        if any(keyword in query_lower for keyword in action_keywords):
            return 'action'
        
        # Specific queries (names, dates, specific labels)
        specific_patterns = ['from:', 'to:', 'label:', 'subject:', '@', '.com', 'from ']
        has_capitalized = any(word[0].isupper() for word in query.split() if len(word) > 1 and word not in COMMON_ENTITY_STOPWORDS)
        has_specific_pattern = any(pattern in query_lower for pattern in specific_patterns)
        
        if (has_capitalized or has_specific_pattern) and 'from' in query_lower:
             return 'sender'
        
        if has_capitalized or has_specific_pattern:
             if '@' in query:
                 return 'sender'
             return 'specific'

        # Rank specific intents higher than generic 'search'
        if any(term in query_lower for term in ['urgent', 'important', 'priority']):
            return 'priority'
        elif any(term in query_lower for term in ['new', 'recent', 'latest', 'unread', 'today', 'yesterday', 'this week']):
            return 'recent'
        elif any(term in query_lower for term in ['from', 'sender', 'by']):
            return 'sender'
        elif any(term in query_lower for term in ['about', 'regarding', 'concerning', 'topic']):
            return 'topic'
        elif any(term in query_lower for term in ['today', 'yesterday', 'week', 'month']):
            return 'temporal'
        
        # Generic intent patterns
        if any(term in query_lower for term in ['find', 'search', 'show', 'get', 'list']):
            return 'search'
            
        return 'search'
            
    def _detect_intent(self, query: str) -> str:
        """Internal wrapper for detect_intent."""
        return self._detect_intent_static(query)
    
    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities from query using spaCy NER and regex."""
        entities = {
            'senders': [],
            'subjects': [],
            'keywords': [],
            'people': [],
            'orgs': []
        }
        
        # Extract email addresses (Regex)
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        entities['senders'] = emails
        
        # Extract quoted strings
        quoted_pattern = r'"([^"]+)"'
        quoted = re.findall(quoted_pattern, query)
        entities['subjects'] = quoted
        
        # spaCy NER
        if self.nlp:
            doc = self.nlp(query)
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    entities['people'].append(ent.text)
                elif ent.label_ == "ORG":
                    entities['orgs'].append(ent.text)
        
        # Fallback/Additional Keyword logic if no NER results or simply to capture capitalized words
        # (Useful if spaCy model assumes sentence case, but queries are often lowercase)
        # We process query manually too
        words = query.split()
        capitalized = []
        for w in words:
            clean_w = w.strip('.,?!:;"\'')
            if (len(clean_w) > 2 and 
                clean_w[0].isupper() and 
                clean_w not in COMMON_ENTITY_STOPWORDS):
                capitalized.append(clean_w)
                
        # Merge capitalized with NER results
        for kw in capitalized:
            if kw not in entities['people'] and kw not in entities['orgs']:
                if len(entities['keywords']) < 5:
                    entities['keywords'].append(kw)
        
        # Also add NER entities to keywords for search
        for person in entities['people']:
             if person not in entities['keywords']:
                 entities['keywords'].append(person)
        for org in entities['orgs']:
             if org not in entities['keywords']:
                 entities['keywords'].append(org)

        return entities
    
    def _extract_temporal(self, query: str) -> Any:
        """Extract temporal constraints using dateparser and regex."""
        query_lower = query.lower()
        
        # 1. Regex/Dictionary Match (Legacy but fast/specific)
        matched_key = None
        for pattern, key in TEMPORAL_PATTERNS.items():
            if re.search(pattern, query_lower):
                matched_key = key
                break
        
        # 2. Dateparser (Advanced)
        # Parse logic: relative entries like "2 days ago", "last friday"
        parsed_date = dateparser.parse(query, settings={'PREFER_DATES_FROM': 'past', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if parsed_date:
            return {
                'key': matched_key or 'specific_date',
                'date': parsed_date,
                'description': query  # Or specific substring if extracted
            }
            
        return matched_key
    
    def _expand_query(self, query: str) -> str:
        """Expand query with synonyms and content-based urgency recognition."""
        words = query.split()
        expanded_words = []
        
        # Check if query is about urgent/important emails using imported patterns
        query_lower = query.lower()
        is_urgent_query = any(term in query_lower for term in ['urgent', 'important', 'priority', 'critical'])
        
        for word in words:
            word_lower = word.lower()
            # Check for synonyms in INSTANCE dict
            if word_lower in self.synonyms:
                # Add original word and synonyms
                expanded_words.append(word)
                expanded_words.extend(self.synonyms[word_lower][:2])  # Add top 2 synonyms
            else:
                expanded_words.append(word)
        
        # If query is about urgent emails, add content-based urgency keywords
        if is_urgent_query:
            # Use subset of important content keywords for expansion
            # We select a few representative ones to avoid exploding the query
            expanded_words.extend(['action required', 'deadline', 'due', 'alert'])
        
        return ' '.join(expanded_words)
    
    def _reformulate_query(self, query: str, intent: str, entities: Dict[str, Any]) -> List[str]:
        """Generate query reformulations."""
        variants = [query]  # Always include original
        
        # Intent-based reformulations
        if intent == 'recent':
            variants.append(f"recent {query}")
            variants.append(f"latest {query}")
        elif intent == 'priority':
            variants.append(f"urgent {query}")
            variants.append(f"important {query}")
        elif intent == 'sender' and entities['senders']:
            # Focus on sender
            sender = entities['senders'][0]
            variants.append(f"emails from {sender}")
        
        # Remove duplicates
        return list(dict.fromkeys(variants))[:5]  # Limit to 5 variants
    
    
    async def _llm_expand_query(self, query: str, intent: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Use LLM to expand query (async) with context support."""
        if not self.llm_client:
            return None
        
        try:
            user_context_info = ""
            if context:
                # Add relevant context if available
                if 'user_role' in context:
                    user_context_info += f"User Role: {context['user_role']}\n"
                if 'current_time' in context:
                     user_context_info += f"Current Time: {context['current_time']}\n"
            
            prompt = f"""Expand this search query with related terms and synonyms to improve search accuracy.
{user_context_info}
Query: "{query}"
Intent: {intent}

Provide 3-5 related terms or synonyms that would help find relevant results. Return only the terms, separated by spaces."""
            
            # Check if client has async invoke
            if hasattr(self.llm_client, 'ainvoke'):
                response = await self.llm_client.ainvoke(prompt)
            else:
                # Fallback to sync invoke if no async method
                response = self.llm_client.invoke(prompt)
                
            if hasattr(response, 'content'):
                return response.content.strip()
            return str(response).strip()
        except Exception as e:
            logger.debug(f"LLM query expansion failed: {e}")
            return None

