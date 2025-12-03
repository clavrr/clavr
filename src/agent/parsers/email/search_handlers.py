"""
Email Search Handlers - Advanced search query building and keyword expansion

This module handles the construction of complex Gmail search queries with:
- Multiple filter types (dates, senders, keywords, etc.)
- Context-aware search using conversation memory
- Keyword expansion with synonyms
- Priority/urgent email detection
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import re
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for search handlers
MAX_SNIPPET_LENGTH = 200
MAX_SUBJECT_PREVIEW_LENGTH = 50
MAX_PREVIEW_LENGTH = 100


class EmailSearchHandlers:
    """Handles advanced search query construction and keyword expansion"""
    
    def __init__(self, parser):
        """
        Initialize search handlers
        
        Args:
            parser: Reference to the parent EmailParser instance
        """
        self.parser = parser
        self.memory = parser.memory
        self.date_parser = parser.date_parser
    
    def build_advanced_search_query(self, classification: Dict[str, Any], user_id: Optional[int], 
                                    session_id: Optional[str], query: str = "") -> str:
        """
        Build advanced Gmail search query with multiple filters
        
        CRITICAL: For priority/urgent queries, return search query for ACTUAL priority emails
        (unread, important, starred) NOT literal words "priority" or "urgent"
        
        Args:
            classification: Classification result with intent and entities
            user_id: User ID for context
            session_id: Session ID for context
            query: Original user query
            
        Returns:
            Gmail search query string
        """
        # CRITICAL: Check for priority queries FIRST
        query_lower = query.lower() if query else ""
        is_priority_query = any(term in query_lower for term in ["priority", "urgent", "immediate attention", "important"])
        
        if is_priority_query:
            # For priority queries, search for ALL emails in inbox (unread + read)
            # We'll filter client-side to find:
            # 1. UNREAD emails (definitely unanswered)
            # 2. READ emails that are original (not replies) - these might need replies
            # Priority = UNREAD emails OR read emails in inbox that might need replies
            # Use empty query - email_tool will use labelIds=['INBOX'] to fetch all inbox emails
            search_query = ""  # Empty query - email_tool will handle fetching all inbox emails
            logger.info(f"[EMAIL] build_advanced_search_query: Priority query detected - using empty query (will fetch ALL inbox emails via labelIds, filter client-side): '{search_query}'")
            return search_query
        
        filters = []
        entities = classification.get('entities', {})
        query_lower = query.lower() if query else ""
        
        # PHASE 2: Context-aware search
        if user_id and session_id and self.memory:
            contextual_query = self.build_contextual_search_query(classification, user_id, session_id)
            if contextual_query:
                filters.append(contextual_query)
        
        # Handle "new" keyword - add recent date filter (last 24-48 hours)
        # "New" means recent: minutes, hours, or a day ago, not weeks/months
        # CRITICAL: Handle "last hour" / "past hour" / "few hours" queries
        time_based_patterns = [
            (r'last\s+hour|past\s+hour', 1),
            (r'last\s+(\d+)\s+hours?|past\s+(\d+)\s+hours?', None),  # Will extract number
            (r'few\s+hours?', 2),
        ]
        
        for pattern, default_hours in time_based_patterns:
            match = re.search(pattern, query_lower)
            if match:
                hours = default_hours
                if default_hours is None:
                    # Extract number from match
                    hours = int(match.group(1) or match.group(2) or 1)
                
                now_utc = datetime.now(timezone.utc)
                start_time = now_utc - timedelta(hours=hours)
                start_str = start_time.strftime("%Y/%m/%d")
                filters.append(f"after:{start_str}")
                logger.info(f"[EMAIL] Added 'last {hours} hour(s)' date filter: after {start_str}")
                break
        
        if "new" in query_lower and not any(word in query_lower for word in ["week", "month", "year", "ago", "hour"]):
            # Check if there's already a date_range from classification
            date_range = entities.get('date_range')
            if not date_range:
                # Add date filter for recent emails (last 48 hours)
                now_utc = datetime.now(timezone.utc)
                # Go back RECENT_EMAIL_HOURS for "new" emails
                recent_start = now_utc - timedelta(hours=EmailParserConfig.RECENT_EMAIL_HOURS)
                recent_start_str = recent_start.strftime("%Y/%m/%d")
                filters.append(f"after:{recent_start_str}")
                logger.info(f"[EMAIL] Added 'new' date filter: after {recent_start_str} (last {EmailParserConfig.RECENT_EMAIL_HOURS} hours)")
        
        # Date range from classification (if not already handled by "new" filter)
        date_range = entities.get('date_range')
        if date_range and self.date_parser:
            if isinstance(date_range, dict):
                start = date_range.get('start')
                end = date_range.get('end')
                if start:
                    filters.append(f"after:{self.date_parser.format_date_for_gmail(datetime.fromisoformat(start))}")
                if end:
                    filters.append(f"before:{self.date_parser.format_date_for_gmail(datetime.fromisoformat(end))}")
            elif isinstance(date_range, str):
                # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                parsed_tuple = self.date_parser.parse(date_range)
                if parsed_tuple and isinstance(parsed_tuple, tuple) and len(parsed_tuple) == 2:
                    start, end = parsed_tuple
                    # Format dates for Gmail (YYYY/MM/DD format)
                    after_date = start.strftime("%Y/%m/%d") if isinstance(start, datetime) else str(start)
                    before_date = end.strftime("%Y/%m/%d") if isinstance(end, datetime) else str(end)
                    filters.append(f"after:{after_date}")
                    filters.append(f"before:{before_date}")
        
        # Senders - check both entities and fallback to direct extraction from query
        senders = entities.get('senders', [])
        
        # CRITICAL: Also extract senders from "or" queries (e.g., "Amex Recruiting or American Express")
        # Check if query contains "or" with senders
        query_for_extraction = query or classification.get('query', '')
        if query_for_extraction and ' or ' in query_for_extraction.lower():
            # Extract all senders from "or" query
            # Pattern: "from X or Y" or "from X or Y or Z"
            or_pattern = r'from\s+([^?]+?)(?:\s*\?|$)'
            or_match = re.search(or_pattern, query_for_extraction, re.IGNORECASE)
            if or_match:
                sender_text = or_match.group(1).strip()
                # Split by "or" and clean each sender
                or_senders = re.split(r'\s+or\s+', sender_text, flags=re.IGNORECASE)
                cleaned_senders = []
                for s in or_senders:
                    s = s.strip()
                    # Remove trailing question words
                    s = re.sub(r'\s+(what|about|is|the|email|emails|\?).*$', '', s, flags=re.IGNORECASE)
                    s = s.rstrip('?').strip()
                    if s and len(s) > 1:
                        skip_words = ['did', 'does', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'about', 'any']
                        if s.lower() not in skip_words:
                            cleaned_senders.append(s)
                if cleaned_senders:
                    logger.info(f"[EMAIL] Extracted {len(cleaned_senders)} senders from 'or' query: {cleaned_senders}")
                    senders = cleaned_senders
        
        # Fallback: If LLM didn't extract sender but query mentions one, extract it directly
        if not senders:
            if query_for_extraction:
                extracted_sender = self.parser._extract_sender_from_query(query_for_extraction)
                if extracted_sender:
                    logger.info(f"[EMAIL] LLM didn't extract sender, but found '{extracted_sender}' via direct extraction")
                    senders = [extracted_sender]
        
        if senders:
            if len(senders) == 1:
                # Quote multi-word senders for Gmail search
                sender = senders[0]
                if ' ' in sender:
                    filters.append(f'from:"{sender}"')
                else:
                    filters.append(f"from:{sender}")
            else:
                # Multiple senders - use OR query with proper quoting
                sender_filters = []
                for s in senders:
                    if ' ' in s:
                        sender_filters.append(f'from:"{s}"')
                    else:
                        sender_filters.append(f"from:{s}")
                sender_filter = " OR ".join(sender_filters)
                filters.append(f"({sender_filter})")
        
        # Keywords (Query expansion)
        keywords = entities.get('keywords', [])
        if keywords:
            # Expand with synonyms
            expanded_keywords = self.expand_keywords(keywords)
            keyword_filter = " OR ".join(expanded_keywords)
            filters.append(f"({keyword_filter})")
        
        # Additional filters
        extra_filters = classification.get('filters', [])
        
        # IMPORTANT: When user asks for "new" email with a sender, they mean MOST RECENT (not unread)
        # Only add is:unread if:
        # 1. User explicitly says "unread" OR
        # 2. User says "new" WITHOUT a sender (then it means unread emails in general)
        # But if user says "new email from [sender]", they want the most recent email from that sender, regardless of read status
        has_sender = bool(senders)
        is_new_query = "new" in query_lower or "latest" in query_lower or "recent" in query_lower
        
        if 'unread' in extra_filters:
            # Only add unread filter if user explicitly said "unread" OR if it's a general "new emails" query without sender
            if not (is_new_query and has_sender):
                filters.append("is:unread")
                logger.info(f"[EMAIL] Added 'is:unread' filter (explicit or general new emails query)")
            else:
                logger.info(f"[EMAIL] Skipping 'is:unread' filter - user wants most recent email from sender, not unread")
        
        if 'important' in extra_filters:
            filters.append("is:important")
        if 'attachment' in extra_filters or 'attachments' in extra_filters:
            filters.append("has:attachment")
        
        # Combine all filters
        search_query = " ".join(filters) if filters else "in:inbox"
        logger.info(f"Built advanced search query: {search_query}")
        return search_query
    
    def build_contextual_search_query(self, classification: Dict[str, Any], user_id: int, session_id: str) -> str:
        """
        Build search query using conversation context
        
        Args:
            classification: Classification result
            user_id: User ID
            session_id: Session ID
            
        Returns:
            Contextual search query string
        """
        try:
            context = self.parser.get_conversation_context(user_id, session_id)
            mentioned_senders = context.get('mentioned_senders', [])
            
            query_lower = classification.get('query', '').lower()
            if "that email" in query_lower or "the email" in query_lower:
                if mentioned_senders:
                    return f"from:{mentioned_senders[0]}"
        except Exception as e:
            logger.debug(f"Could not build contextual query: {e}")
        
        return ""
    
    def expand_keywords(self, keywords: List[str]) -> List[str]:
        """
        Expand keywords with synonyms - integrates learned patterns
        
        Args:
            keywords: List of keywords to expand
            
        Returns:
            Expanded list of keywords with synonyms
        """
        # Start with built-in synonyms
        synonym_map = {
            "email": ["message", "mail"],
            "important": ["urgent", "critical"],
            "project": ["initiative", "work"],
            "meeting": ["appointment", "call"],
        }
        
        # Merge with learned synonyms from feedback
        learned_synonyms = getattr(self.parser, '_learned_synonyms', {})
        for keyword, synonyms in learned_synonyms.items():
            if keyword in synonym_map:
                synonym_map[keyword].extend(synonyms)
            else:
                synonym_map[keyword] = synonyms
        
        expanded = []
        for keyword in keywords:
            expanded.append(keyword)
            if keyword.lower() in synonym_map:
                expanded.extend(synonym_map[keyword.lower()][:1])
        
        return expanded

    def should_use_hybrid_search(self, query: str) -> bool:
        """
        Determine if query should use hybrid search (both RAG and direct search)
        
        Hybrid search is beneficial for complex queries that combine:
        - Structured filters (sender, date) AND semantic concepts (topic, meaning)
        - Example: "emails from John about budget" = sender (direct) + topic (RAG)
        
        Args:
            query: User query string
            
        Returns:
            True if hybrid search should be used
        """
        import re
        query_lower = query.lower()
        
        # Check if query combines structured AND semantic elements
        
        # Has structured elements (sender, date, folder, operators)
        has_sender = bool(re.search(r'\bfrom\s+[a-zA-Z]', query_lower))
        has_date = any(indicator in query_lower for indicator in 
                      ['today', 'yesterday', 'last week', 'this week', 'after:', 'before:'])
        has_operators = bool(re.search(r'(subject|has|is|in|label):', query_lower))
        has_folder = any(indicator in query_lower for indicator in 
                        ['in inbox', 'in sent', 'in trash', 'in spam'])
        has_structured = has_sender or has_date or has_operators or has_folder
        
        # Has semantic elements (topic, abstract concepts)
        has_topic = bool(re.search(
            r'\b(about|regarding|concerning|related to|emails about|emails regarding)\s+[a-z]+', 
            query_lower))
        has_abstract = any(concept in query_lower for concept in 
                          ['urgent', 'important', 'discussions', 'meetings', 'decisions'])
        has_semantic = has_topic or has_abstract
        
        # Use hybrid if BOTH structured AND semantic elements are present
        if has_structured and has_semantic:
            logger.info(f"[EMAIL] Query combines structured + semantic - using hybrid search: '{query}'")
            return True
        
        return False

    def should_use_rag(self, query: str) -> bool:
        """
        Determine if query should use RAG semantic search vs direct Gmail search
        
        Returns True for semantic/topic queries, False for structured queries.
        This enables intelligent routing between direct search (fast, accurate for structured queries)
        and RAG search (better for semantic/topic-based queries).
        
        Args:
            query: User query string
            
        Returns:
            True if RAG should be used, False for direct Gmail search
        """
        import re
        query_lower = query.lower()
        
        # Check hybrid first - if hybrid is needed, don't use pure RAG
        if self.should_use_hybrid_search(query):
            return False  # Hybrid will handle it
        
        # Use DIRECT SEARCH for structured queries (most common - ~80% of queries):
        
        # 1. Sender-based queries: "from X", "emails from X"
        if re.search(r'\bfrom\s+[a-zA-Z]', query_lower):
            logger.info(f"[EMAIL] Query contains sender - using direct search: '{query}'")
            return False
        
        # 2. Date-based queries: "today", "yesterday", "last week", "after:", "before:"
        # CRITICAL: Include time-based phrases like "last hour", "past hour", etc.
        date_indicators = ['today', 'yesterday', 'last week', 'this week', 'last month', 
                          'this month', 'last hour', 'past hour', 'last day', 'past day',
                          'few hours', 'few days', 'last year', 'this year',
                          'after:', 'before:', 'newer_than:', 'older_than:']
        if any(indicator in query_lower for indicator in date_indicators):
            logger.info(f"[EMAIL] Query contains date filter - using direct search: '{query}'")
            return False
        
        # 3. Explicit Gmail search operators: "subject:", "has:", "is:", "in:"
        if re.search(r'(subject|has|is|in|label|filename|size|larger|smaller):', query_lower):
            logger.info(f"[EMAIL] Query contains Gmail operators - using direct search: '{query}'")
            return False
        
        # 4. Folder-based queries: "in inbox", "in sent", "in trash"
        folder_indicators = ['in inbox', 'in sent', 'in trash', 'in spam', 'in drafts', 
                           'in archive', 'in starred', 'in important']
        if any(indicator in query_lower for indicator in folder_indicators):
            logger.info(f"[EMAIL] Query specifies folder - using direct search: '{query}'")
            return False
        
        # Use RAG for semantic/topic queries (~15% of queries):
        
        # 1. Topic-based queries: "about budget", "regarding project", "emails about X"
        topic_patterns = [
            r'\b(about|regarding|concerning|related to|emails about|emails regarding|emails concerning)\s+[a-z]+',
            r'\bemails?\s+(about|regarding|concerning|related to)\s+[a-z]+',
        ]
        for pattern in topic_patterns:
            if re.search(pattern, query_lower):
                logger.info(f"[EMAIL] Query is topic-based - using RAG: '{query}'")
                return True
        
        # 2. Abstract concept queries: "urgent", "important discussions", "meeting-related"
        # Only if NOT combined with sender (sender queries should use direct search)
        abstract_concepts = ['urgent', 'important', 'discussions', 'meetings', 'decisions', 
                           'action items', 'follow-ups', 'pending', 'unresolved']
        if any(concept in query_lower for concept in abstract_concepts):
            # Check if it's combined with sender - if so, use direct search
            if not re.search(r'\bfrom\s+[a-zA-Z]', query_lower):
                logger.info(f"[EMAIL] Query contains abstract concepts - using RAG: '{query}'")
                return True
        
        # 3. Similarity queries: "find similar", "like this", "related emails"
        similarity_patterns = ['similar', 'like this', 'related emails', 'find similar', 
                             'emails like', 'similar to', 'same topic']
        if any(pattern in query_lower for pattern in similarity_patterns):
            logger.info(f"[EMAIL] Query asks for similarity - using RAG: '{query}'")
            return True
        
        # 4. Semantic search explicit requests
        if any(phrase in query_lower for phrase in ['semantic search', 'semantic', 'find by meaning']):
            logger.info(f"[EMAIL] Query explicitly requests semantic search - using RAG: '{query}'")
            return True
        
        # Default: Use direct search (faster, more accurate for most queries)
        logger.info(f"[EMAIL] Default routing - using direct search: '{query}'")
        return False

    def hybrid_search(self, tool: BaseTool, query: str, search_query: str, folder: str, limit: int) -> str:
        """
        Perform hybrid search combining both direct Gmail search and RAG semantic search
        
        This method:
        1. Runs both direct search and RAG search in parallel
        2. Extracts email IDs from both result sets
        3. Deduplicates by message ID
        4. Ranks results (direct search results prioritized, then RAG results)
        5. Formats merged results
        
        Args:
            tool: Email tool instance
            query: Original user query
            search_query: Extracted search query
            folder: Target folder
            limit: Maximum number of results
            
        Returns:
            Formatted search results combining both methods
        """
        import re
        from datetime import datetime, timezone
        
        logger.info(f"[EMAIL] Starting hybrid search for query: '{query}'")
        
        # Extract structured and semantic parts of the query
        query_lower = query.lower()
        
        # Check if this is a priority query
        is_priority_query = any(term in query_lower for term in ["priority", "urgent", "immediate attention", "important"])
        
        # Build direct search query (structured part)
        direct_query = search_query or ""
        
        # Build RAG query (semantic part - extract topic/concept)
        if is_priority_query:
            # For priority queries, enhance RAG query to find emails semantically matching priority/urgent
            # RAG can find emails that need attention even if they don't have exact keywords
            # This helps find emails from recruiters, friends, companies that need replies based on content
            rag_query = "priority emails that need immediate attention, require response, or need action"
            # Also include the original query for context
            rag_query = f"{rag_query} {query}"
            logger.info(f"[EMAIL] Priority query detected - using enhanced RAG query for semantic priority detection: '{rag_query}'")
        else:
            rag_query = query
            # Remove structured parts for RAG query
            rag_query = re.sub(r'\bfrom\s+[a-zA-Z][a-zA-Z0-9@._-]+', '', rag_query, flags=re.IGNORECASE)
            rag_query = re.sub(r'\b(after|before|newer_than|older_than):[^\s]+', '', rag_query, flags=re.IGNORECASE)
            rag_query = re.sub(r'\b(in|is|has|subject|label):[^\s]+', '', rag_query, flags=re.IGNORECASE)
            rag_query = re.sub(r'\s+', ' ', rag_query).strip()
            
            if not rag_query or len(rag_query) < 3:
                rag_query = query  # Fallback to full query
        
        logger.info(f"[EMAIL] Hybrid search - Direct query: '{direct_query}', RAG query: '{rag_query}'")
        
        # Run both searches
        direct_results = []
        rag_results = []
        
            # 1. Run direct search
        direct_results_empty = False
        try:
            # For priority queries with empty query, skip date filtering - we want ALL emails
            if is_priority_query and (not direct_query or not direct_query.strip()):
                # Empty query for priority - fetch all inbox emails, filter client-side
                logger.info(f"[EMAIL] Priority query with empty direct_query - fetching all inbox emails")
                direct_result_str = tool._run(action="search", query="", folder=folder, limit=limit * 2)
            else:
                # Handle "new" keyword for direct search (non-priority queries)
                if "new" in query_lower and not any(word in query_lower for word in ["week", "month", "year", "ago"]):
                    from datetime import timedelta
                    now_utc = datetime.now(timezone.utc)
                    recent_start = now_utc - timedelta(hours=48)
                    recent_start_str = recent_start.strftime("%Y/%m/%d")
                    if direct_query and direct_query.strip():
                        direct_query = f"{direct_query} after:{recent_start_str}"
                    else:
                        direct_query = f"after:{recent_start_str}"
                
                direct_result_str = tool._run(action="search", query=direct_query, folder=folder, limit=limit * 2)
            
            # Check if direct search returned empty (API might be restricted)
            if not direct_result_str or not direct_result_str.strip() or "No emails found" in direct_result_str:
                direct_results_empty = True
                logger.warning(f"[EMAIL] Direct search returned empty - API may be restricted. Will rely on RAG search.")
            
            # Extract email details from direct search results
            if direct_result_str and "No emails found" not in direct_result_str:
                # Parse direct search results to extract email IDs
                if hasattr(tool, 'google_client') and tool.google_client:
                    try:
                        # Get actual message objects from Gmail
                        direct_messages = tool.google_client.list_messages(
                            query=direct_query, 
                            max_results=limit * 2,
                            label_ids=[tool.FOLDER_MAP.get(folder.lower(), "INBOX")] if folder != "all" else None
                        )
                        direct_results = direct_messages or []
                        logger.info(f"[EMAIL] Direct search found {len(direct_results)} emails")
                    except Exception as e:
                        logger.warning(f"[EMAIL] Could not get direct search messages: {e}")
                        # Fallback: parse from result string
                        direct_results = self.parser.utility_handlers.extract_emails_from_result_string(direct_result_str, tool)
        except Exception as e:
            logger.warning(f"[EMAIL] Direct search failed in hybrid: {e}")
        
        # 2. Run RAG search
        # CRITICAL: For priority queries, if direct search failed (API restricted), rely heavily on RAG
        try:
            # For priority queries, RAG can find emails that semantically match "priority" even if unread
            # If direct search failed, increase RAG results to compensate
            # This helps find emails that need attention based on content, not just status
            rag_result_str = tool._run(action="semantic_search", query=rag_query, folder=folder, limit=limit * 2)
            
            # Extract email IDs from RAG results
            # CRITICAL: For priority queries, try to get raw RAG results directly (bypass API if restricted)
            if rag_result_str and "No semantically similar" not in rag_result_str:
                # Try to get raw RAG results directly if available (more reliable than parsing formatted string)
                rag_results = []
                if hasattr(tool, 'rag_engine') and tool.rag_engine:
                    try:
                        # Get raw RAG results directly - these contain full email metadata
                        # Use RAGEngine.search() instead of deprecated knowledge_retriever()
                        raw_rag_results = tool.rag_engine.search(
                            rag_query,
                            k=limit * 5 if direct_results_empty else limit * 3,  # Get more if API restricted
                            rerank=True  # Hybrid scoring is automatically applied when rerank=True
                        )
                        logger.info(f"[EMAIL] Got {len(raw_rag_results)} raw RAG results")
                        
                        # Convert RAG results to email format
                        for result in raw_rag_results:
                            metadata = result.get('metadata', {})
                            content = result.get('content', '')
                            
                            # Create email dict from RAG result
                            # Parse labels from metadata (could be string or list)
                            labels = metadata.get('labels', [])
                            if isinstance(labels, str):
                                # If labels is a string, try to parse it
                                try:
                                    import json
                                    labels = json.loads(labels) if labels else []
                                except:
                                    # If not JSON, split by comma or treat as single label
                                    labels = [l.strip() for l in labels.split(',')] if labels else []
                            
                            email_dict = {
                                'id': metadata.get('message_id', ''),
                                'subject': metadata.get('subject', 'No Subject'),
                                'sender': metadata.get('sender', 'Unknown'),
                                'date': metadata.get('timestamp', ''),
                                'snippet': content[:MAX_SNIPPET_LENGTH] if content else '',
                                'body': content,
                                'labels': labels if isinstance(labels, list) else [],
                                'thread_id': metadata.get('thread_id', '')
                            }
                            rag_results.append(email_dict)
                        
                        logger.info(f"[EMAIL] Converted {len(rag_results)} RAG results to email format")
                    except Exception as e:
                        logger.warning(f"[EMAIL] Could not get raw RAG results: {e}, falling back to extraction")
                        # Fallback to extraction method
                        rag_results = self.parser.utility_handlers.extract_emails_from_rag_result(rag_result_str, tool, max_results=limit * 2)
                else:
                    # No RAG tool available, use extraction
                    rag_results = self.parser.utility_handlers.extract_emails_from_rag_result(rag_result_str, tool, max_results=limit * 2)
                
                logger.info(f"[EMAIL] RAG search found {len(rag_results)} emails (semantic priority detection)")
                
                # For priority queries, filter RAG results to include:
                # 1. Unread emails (definitely unanswered)
                # 2. Payment-related emails (always priority)
                # 3. Read emails that are original (not replies) - might need replies
                # 4. Emails from important senders (recruiters, companies, friends)
                if is_priority_query:
                    filtered_rag_results = []
                    for email in rag_results:
                        labels = email.get('labels', [])
                        subject = email.get('subject', '').lower()
                        snippet = email.get('snippet', '').lower()
                        sender = email.get('sender', '').lower()
                        
                        # Check if unread
                        is_unread = 'UNREAD' in labels or any('unread' in str(l).lower() for l in labels)
                        
                        # Check if payment-related
                        is_payment_related = any(payment_term in f"{subject} {snippet}" for payment_term in [
                            'payment', 'pay', 'invoice', 'billing', 'due', 'overdue', 'past due',
                            'missed payment', 'payment method', 'update payment', 'payment failed',
                            'subscription', 'renewal', 'expires', 'expiring', 'deployment failed',
                            'deployment', 'failed', 'error'
                        ])
                        
                        # Check if original email (not a reply) - emails without "Re:" are likely original
                        is_original_email = not subject.startswith('re:') and not subject.startswith('fwd:')
                        
                        # Check if from important senders (recruiters, companies, etc.)
                        is_important_sender = any(term in sender for term in [
                            'recruiter', 'hiring', 'career', 'job', 'opportunity', 'interview',
                            'vercel', 'deployment', 'github', 'notification'
                        ])
                        
                        # Include if:
                        # 1. Unread (definitely unanswered)
                        # 2. Payment-related (always priority)
                        # 3. Original email (not a reply) - might need a reply
                        # 4. From important sender (recruiters, companies)
                        if is_unread or is_payment_related or (is_original_email and is_important_sender):
                            filtered_rag_results.append(email)
                            logger.debug(f"[EMAIL] Including priority email from RAG: {subject[:MAX_SUBJECT_PREVIEW_LENGTH]} (unread={is_unread}, payment={is_payment_related}, original={is_original_email}, important_sender={is_important_sender})")
                    
                    rag_results = filtered_rag_results
                    logger.info(f"[EMAIL] Filtered RAG results for priority query: {len(rag_results)} emails (unread, payment-related, or important original emails)")
            else:
                rag_results = []
        except Exception as e:
            logger.warning(f"[EMAIL] RAG search failed in hybrid: {e}")
        
        # 3. Merge and deduplicate results
        logger.info(f"[EMAIL] Merging results: {len(direct_results)} direct + {len(rag_results)} RAG = {len(direct_results) + len(rag_results)} total")
        merged_results = self.parser.utility_handlers.merge_search_results(direct_results, rag_results, limit)
        logger.info(f"[EMAIL] After merge: {len(merged_results)} emails")
        
        # 4. Format merged results
        if not merged_results:
            # Return empty - let LLM generate conversational response
            logger.warning(f"[EMAIL] No merged results - direct={len(direct_results)}, RAG={len(rag_results)}")
            return ""
        
        # Format output (no hardcoded "I found" - LLM will generate natural response)
        output = ""
        
        for i, email in enumerate(merged_results, 1):
            sender = email.get('sender', 'Unknown')
            subject = email.get('subject', '(No Subject)')
            timestamp = email.get('date', '') or email.get('timestamp', '')
            
            # Format timestamp
            try:
                if timestamp:
                    if isinstance(timestamp, str):
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(timestamp)
                        if dt.tzinfo is not None:
                            dt = dt.astimezone()
                        formatted_time = dt.strftime('%Y-%m-%d %H:%M')
                    else:
                        formatted_time = str(timestamp)
                else:
                    formatted_time = "Unknown time"
            except:
                formatted_time = str(timestamp) if timestamp else "Unknown time"
            
            # Check if unread
            labels = email.get('labels', [])
            unread_icon = "[UNREAD]" if "UNREAD" in labels else "[READ]"
            
            # Add source indicator
            source = email.get('_source', 'direct')
            source_tag = " [Direct]" if source == 'direct' else " [Semantic]"
            
            output += f"{i}. {unread_icon}{source_tag} **{subject}**\n"
            output += f"   From: {sender}\n"
            output += f"   Time: {formatted_time}\n"
            if email.get('body') or email.get('snippet'):
                preview = (email.get('body') or email.get('snippet', ''))[:MAX_PREVIEW_LENGTH].replace('\n', ' ')
                output += f"   Preview: {preview}...\n"
            output += "\n"
        
        # Return formatted output directly (no [EMAIL] prefix) - final safeguard will make it conversational
        return output.strip()
