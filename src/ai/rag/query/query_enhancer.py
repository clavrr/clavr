"""
Query Enhancement Module

Improves RAG accuracy by enhancing queries before retrieval.
Includes query expansion, reformulation, and intent understanding.
"""
import re
from typing import List, Dict, Any, Optional
from ....utils.logger import setup_logger
from ..utils.utils import extract_keywords

logger = setup_logger(__name__)


class QueryEnhancer:
    """
    Enhances queries for better RAG retrieval accuracy.
    
    Features:
    - Query expansion with synonyms
    - Intent understanding
    - Query reformulation
    - Entity extraction
    - Temporal understanding
    """
    
    # Common synonyms and related terms (email-specific)
    SYNONYMS = {
        'new': ['recent', 'latest', 'fresh', 'current', 'unread', 'newest'],
        'old': ['previous', 'past', 'earlier', 'archived', 'older'],
        'urgent': ['important', 'priority', 'critical', 'immediate', 'asap', 'urgent'],
        'meeting': ['appointment', 'call', 'conference', 'session', 'meeting'],
        'email': ['message', 'mail', 'correspondence', 'email', 'emails', 'messages'],
        'task': ['todo', 'action', 'item', 'work', 'task', 'tasks'],
        'deadline': ['due date', 'due', 'deadline', 'cutoff'],
        'message': ['email', 'mail', 'correspondence', 'message', 'messages'],
        'mail': ['email', 'message', 'correspondence', 'mail'],
        'find': ['search', 'locate', 'get', 'show', 'list'],
        'show': ['display', 'list', 'find', 'get'],
        'from': ['by', 'sent by', 'sender'],
    }
    
    # Content-based urgency/importance indicators (not domain-specific)
    # These patterns help identify urgent/important emails based on content, not sender
    URGENCY_SUBJECT_PATTERNS = {
        'urgent', 'important', 'priority', 'critical', 'asap', 'as soon as possible',
        'action required', 'action needed', 'please respond', 'response needed',
        'deadline', 'due date', 'due today', 'overdue',
        'security alert', 'security', 'alert', 'warning', 'notification',
        'payment', 'billing', 'invoice', 'receipt', 'account',
        'verification', 'verify', 'confirm', 'confirmation',
        'meeting', 'appointment', 'call', 'schedule',
        'emergency', 'immediate', 'time sensitive'
    }
    
    # Content keywords that indicate importance (from email body)
    IMPORTANCE_CONTENT_KEYWORDS = {
        'deadline', 'due', 'urgent', 'important', 'priority', 'asap',
        'meeting', 'appointment', 'call', 'schedule', 'cancel',
        'payment', 'invoice', 'billing', 'account', 'security',
        'verification', 'confirm', 'action required', 'please respond',
        'project', 'assignment', 'homework', 'exam', 'test', 'grade',
        'interview', 'offer', 'job', 'opportunity', 'contract'
    }
    
    # Sender patterns that might indicate automated/notification emails
    # (but not hardcoded domains - these are patterns, not specific companies)
    NOTIFICATION_SENDER_PATTERNS = {
        'noreply', 'no-reply', 'notifications', 'alerts', 'notify',
        'automated', 'system', 'do-not-reply', 'donotreply'
    }
    
    # Temporal patterns
    TEMPORAL_PATTERNS = {
        r'\btoday\b': 'today',
        r'\byesterday\b': 'yesterday',
        r'\btomorrow\b': 'tomorrow',
        r'\bthis week\b': 'this_week',
        r'\blast week\b': 'last_week',
        r'\bnext week\b': 'next_week',
        r'\bthis month\b': 'this_month',
        r'\blast month\b': 'last_month',
        r'\brecent\b': 'recent',
        r'\bnew\b': 'recent',
    }
    
    def __init__(self, use_llm_expansion: bool = False, llm_client: Optional[Any] = None):
        """
        Initialize query enhancer.
        
        Args:
            use_llm_expansion: Use LLM for query expansion (more accurate but slower)
            llm_client: Optional LLM client for advanced expansion
        """
        self.use_llm_expansion = use_llm_expansion
        self.llm_client = llm_client
    
    def enhance(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance a query for better retrieval.
        
        Args:
            query: Original query
            context: Optional context (e.g., user preferences, recent queries)
            
        Returns:
            Enhanced query dictionary with:
            - original: Original query
            - expanded: Expanded query with synonyms
            - reformulated: Reformulated query variants
            - intent: Detected intent
            - entities: Extracted entities
            - temporal: Temporal constraints
        """
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
                llm_expanded = self._llm_expand_query(original, intent)
                if llm_expanded:
                    expanded = f"{expanded} {llm_expanded}".strip()
            except Exception as e:
                logger.debug(f"LLM expansion failed: {e}")
        
        return {
            'original': original,
            'expanded': expanded,
            'reformulated': reformulated,
            'intent': intent,
            'entities': entities,
            'temporal': temporal,
            'keywords': extract_keywords(expanded)
        }
    
    def _detect_intent(self, query: str) -> str:
        """Detect query intent."""
        query_lower = query.lower()
        
        # Financial/spending queries (check first as they're specific)
        if any(term in query_lower for term in ['spend', 'spent', 'cost', 'paid', 'payment', 'receipt', 
                                                'invoice', 'total', 'amount', 'how much', 'expense', 'expenses']):
            return 'financial'
        
        # Intent patterns
        if any(term in query_lower for term in ['find', 'search', 'show', 'get', 'list']):
            return 'search'
        elif any(term in query_lower for term in ['new', 'recent', 'latest', 'unread']):
            return 'recent'
        elif any(term in query_lower for term in ['urgent', 'important', 'priority']):
            return 'priority'
        elif any(term in query_lower for term in ['from', 'sender', 'by']):
            return 'sender'
        elif any(term in query_lower for term in ['about', 'regarding', 'concerning', 'topic']):
            return 'topic'
        elif any(term in query_lower for term in ['today', 'yesterday', 'week', 'month']):
            return 'temporal'
        else:
            return 'general'
    
    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities from query."""
        entities = {
            'senders': [],
            'subjects': [],
            'keywords': []
        }
        
        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        entities['senders'] = emails
        
        # Extract quoted strings (likely subjects)
        quoted_pattern = r'"([^"]+)"'
        quoted = re.findall(quoted_pattern, query)
        entities['subjects'] = quoted
        
        # Extract keywords (capitalized words might be names/entities)
        words = query.split()
        capitalized = [w for w in words if w[0].isupper() and len(w) > 2]
        entities['keywords'] = capitalized[:5]  # Limit to 5
        
        return entities
    
    def _extract_temporal(self, query: str) -> Optional[str]:
        """Extract temporal constraints."""
        query_lower = query.lower()
        
        for pattern, temporal in self.TEMPORAL_PATTERNS.items():
            if re.search(pattern, query_lower):
                return temporal
        
        return None
    
    def _expand_query(self, query: str) -> str:
        """Expand query with synonyms and content-based urgency recognition."""
        words = query.split()
        expanded_words = []
        
        # Check if query is about urgent/important emails
        query_lower = query.lower()
        is_urgent_query = any(term in query_lower for term in ['urgent', 'important', 'priority', 'critical'])
        
        for word in words:
            word_lower = word.lower()
            # Check for synonyms
            if word_lower in self.SYNONYMS:
                # Add original word and synonyms
                expanded_words.append(word)
                expanded_words.extend(self.SYNONYMS[word_lower][:2])  # Add top 2 synonyms
            else:
                expanded_words.append(word)
        
        # If query is about urgent emails, add content-based urgency keywords
        # These help match emails with urgent content regardless of sender
        if is_urgent_query:
            # Add content-based urgency indicators (not domain-specific)
            expanded_words.extend(['action required', 'deadline', 'security', 'alert', 'notification'])
        
        return ' '.join(expanded_words)
    
    @staticmethod
    def detect_content_urgency(subject: str, content: str, metadata: Dict[str, Any]) -> float:
        """
        Detect urgency/importance based on email content, not sender domain.
        
        Args:
            subject: Email subject line
            content: Email body content
            metadata: Email metadata (read status, important flag, etc.)
            
        Returns:
            Urgency score (0.0 to 1.0)
        """
        urgency_score = 0.0
        subject_lower = subject.lower() if subject else ''
        content_lower = content.lower() if content else ''
        combined_text = f"{subject_lower} {content_lower}"
        
        # Check subject line for urgency indicators
        subject_urgency_matches = sum(
            1 for pattern in QueryEnhancer.URGENCY_SUBJECT_PATTERNS
            if pattern in subject_lower
        )
        if subject_urgency_matches > 0:
            # More matches = higher urgency
            urgency_score += min(0.4, subject_urgency_matches * 0.1)
        
        # Check content for importance keywords
        content_importance_matches = sum(
            1 for keyword in QueryEnhancer.IMPORTANCE_CONTENT_KEYWORDS
            if keyword in combined_text
        )
        if content_importance_matches > 0:
            # More matches = higher importance
            urgency_score += min(0.3, content_importance_matches * 0.05)
        
        # Boost for unread emails (might be more urgent)
        if metadata.get('read', True) == False:
            urgency_score += 0.15
        
        # Boost for explicitly marked important/starred
        if metadata.get('important', False) or metadata.get('starred', False):
            urgency_score += 0.2
        
        # Boost for emails with attachments (might contain important documents)
        if metadata.get('has_attachments', False):
            urgency_score += 0.05
        
        # Boost for recent emails (within last 24 hours)
        timestamp = metadata.get('timestamp', '')
        if timestamp:
            from ..utils.utils import parse_timestamp
            from datetime import datetime
            email_date = parse_timestamp(timestamp)
            if email_date:
                if email_date.tzinfo:
                    hours_old = (datetime.now(email_date.tzinfo) - email_date).total_seconds() / 3600
                else:
                    hours_old = (datetime.now() - email_date.replace(tzinfo=None)).total_seconds() / 3600
                if hours_old < 24:
                    urgency_score += 0.1  # Recent emails might be more urgent
        
        return min(1.0, urgency_score)
    
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
    
    
    def _llm_expand_query(self, query: str, intent: str) -> Optional[str]:
        """Use LLM to expand query (optional, more accurate)."""
        if not self.llm_client:
            return None
        
        try:
            prompt = f"""Expand this search query with related terms and synonyms to improve search accuracy.

Query: "{query}"
Intent: {intent}

Provide 3-5 related terms or synonyms that would help find relevant results. Return only the terms, separated by spaces."""
            
            response = self.llm_client.invoke(prompt)
            if hasattr(response, 'content'):
                return response.content.strip()
            return str(response).strip()
        except Exception as e:
            logger.debug(f"LLM query expansion failed: {e}")
            return None

