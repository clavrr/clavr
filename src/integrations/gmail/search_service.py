"""
Email Search Service - Specialized logic for email search operations
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import re
import asyncio
import pytz

from src.utils.logger import setup_logger
from .exceptions import EmailSearchException, ServiceUnavailableException

logger = setup_logger(__name__)

class EmailSearchService:
    """
    Specialized service for searching and filtering emails
    """
    
    def __init__(self, parent):
        """
        Initialize with parent EmailService to access shared state
        """
        self.parent = parent
        self._original_sender_name = None
    
    @property
    def config(self): return self.parent.config
    @property
    def rag_engine(self): return self.parent.rag_engine
    @property
    def hybrid_coordinator(self): return self.parent.hybrid_coordinator
    @property
    def user_id(self): return self.parent.user_id
    @property
    def date_parser(self): return self.parent.date_parser
    @property
    def llm_client(self): return self.parent.llm_client
    @property
    def gmail_client(self): return self.parent.gmail_client

    def _ensure_available(self):
        self.parent._ensure_available()

    async def _query_graph_for_emails(
        self,
        from_email: Optional[str] = None,
        after_date: Optional[str] = None,
        before_date: Optional[str] = None,
        subject: Optional[str] = None,
        folder: str = "inbox",
        is_unread: Optional[bool] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Query ArangoDB graph database for emails using structured filters (Native AQL)."""
        if not self.hybrid_coordinator or not self.hybrid_coordinator.graph:
            logger.debug("[EMAIL_SEARCH] Graph not available for query")
            return []
        
        try:
            graph = self.hybrid_coordinator.graph
            filters = []
            params = {'limit': limit}
            
            if self.user_id:
                params['user_id'] = self.user_id
                filters.append("e.user_id == @user_id")
            else:
                logger.warning("[EMAIL_SEARCH] SECURITY: No user_id set, refusing to query graph!")
                return []
            
            if from_email:
                params['from_email'] = from_email.lower()
                sender_filter = "(LOWER(e.sender) == @from_email OR CONTAINS(LOWER(e.sender), @from_email) OR CONTAINS(SPLIT(LOWER(e.sender), '@')[0], @from_email))"
                filters.append(sender_filter)
                
            if after_date:
                after_date_graph = after_date.replace('/', '-')
                params['after_date_ts'] = f"{after_date_graph}T00:00:00"
                filters.append("(e.date >= @after_date_ts OR (e.timestamp != null AND e.timestamp >= @after_date_ts))")
                
            if before_date:
                before_date_graph = before_date.replace('/', '-')
                params['before_date_ts'] = f"{before_date_graph}T23:59:59"
                filters.append("(e.date < @before_date_ts OR (e.timestamp != null AND e.timestamp < @before_date_ts))")
                
            if subject:
                params['subject'] = subject
                filters.append("CONTAINS(LOWER(e.subject), LOWER(@subject))")
                
            if folder and folder != 'inbox':
                params['folder'] = folder
                filters.append("e.folder == @folder")
                
            if is_unread is not None:
                params['is_unread'] = is_unread
                filters.append("e.is_unread == @is_unread")
                
            filter_str = " AND ".join(filters) if filters else "true"
            aql_query = f"FOR e IN Email FILTER {filter_str} SORT e.timestamp DESC LIMIT @limit RETURN e"
            
            results = await graph.execute_query(aql_query, params)
            emails = []
            if results:
                for props in results:
                    full_body = props.get('body', '') or ''
                    emails.append({
                        'id': props.get('email_id') or props.get('id', '') or props.get('_key', ''),
                        'threadId': props.get('thread_id', ''),
                        'subject': props.get('subject', 'No Subject'),
                        'sender': props.get('sender', 'Unknown'),
                        'from': props.get('sender', 'Unknown'),
                        'date': props.get('timestamp') or props.get('date', ''),
                        'snippet': full_body[:200],
                        'body': full_body,
                        'labels': props.get('labels', []),
                        'has_attachments': props.get('has_attachments', False),
                        'folder': props.get('folder', folder),
                        '_source': 'graph'
                    })
            return emails
        except Exception as e:
            logger.error(f"[EMAIL_SEARCH] Graph query failed: {e}")
            return []

    async def _resolve_name_to_emails(self, name: str) -> List[str]:
        """Resolve a person's name to their email addresses using the Contact and Person graph (Native AQL)."""
        if not self.hybrid_coordinator or not self.hybrid_coordinator.graph:
            return []
        if not name or len(name.strip()) < 2:
            return []
        try:
            graph = self.hybrid_coordinator.graph
            name_lower = name.lower().strip()
            # Expanded query to include Person nodes (extracted entities)
            # Added filters for system emails to avoid resolving to 'noreply'
            aql_query = """
                LET contacts = (
                    FOR c IN Contact
                        LET name_lower = LOWER(c.name)
                        LET email_lower = LOWER(c.email)
                        FILTER CONTAINS(name_lower, @name) OR CONTAINS(email_lower, @name)
                        RETURN {name: c.name, email: c.email}
                )
                LET people = (
                    FOR p IN Person
                        LET name_lower = LOWER(p.name)
                        LET email_lower = LOWER(p.email)
                        FILTER (CONTAINS(name_lower, @name) OR CONTAINS(email_lower, @name)) AND p.email != null AND p.email != ""
                        RETURN {name: p.name, email: p.email}
                )
                FOR r IN UNION(contacts, people)
                    FILTER r.email != null
                    # Relax no-reply filtering: if it's a known company or the ONLY result, we should keep it
                    # Original logic was too aggressive for billing/receipts
                    LET is_noreply = (CONTAINS(LOWER(r.email), 'noreply') OR CONTAINS(LOWER(r.email), 'no-reply'))
                    # If it's no-reply, only filter it out if we have OTHER better results
                    # But for now, let's just allow it if the name matches well
                    # FILTER NOT CONTAINS(LOWER(r.email), 'noreply') 
                    # FILTER NOT CONTAINS(LOWER(r.email), 'no-reply')
                    
                    FILTER NOT CONTAINS(LOWER(r.email), 'notifications')
                    FILTER NOT CONTAINS(LOWER(r.email), 'alert')
                    FILTER NOT CONTAINS(LOWER(r.email), 'bounce')
                    # Keep support for now as it's often used for billing
                    # FILTER NOT CONTAINS(LOWER(r.email), 'support')
                    
                    SORT is_noreply ASC, r.name ASC 
                    LIMIT 10 
                    RETURN DISTINCT r.email
            """
            return await graph.execute_query(aql_query, params={'name': name_lower})
        except Exception as e:
            logger.warning(f"[EMAIL_SEARCH] Contact/Person resolution failed: {e}")
            return []

    def _resolve_name_to_emails_sync(self, name: str) -> List[str]:
        """Synchronous wrapper for _resolve_name_to_emails."""
        if not name: return []
        try:
            # Always use asyncio.run() in a fresh thread to avoid event loop issues
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(self._resolve_name_to_emails(name))).result(timeout=3.0)
        except Exception as e:
            logger.warning(f"[EMAIL_SEARCH] Sync name resolution failed: {e}")
            return []

    def search_emails(
        self,
        query: Optional[str] = None,
        folder: str = "inbox",
        limit: int = 10,
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        subject: Optional[str] = None,
        has_attachment: Optional[bool] = None,
        after_date: Optional[str] = None,
        before_date: Optional[str] = None,
        is_unread: Optional[bool] = None,
        allow_rag: bool = True
    ) -> List[Dict[str, Any]]:
        """Search emails with filters - Optimized with multi-stage fallback"""
        self._original_sender_name = None
        freshness_keywords = ['new', 'unread', 'latest', 'recent', 'today', 'tonight', 'last hour']
        is_freshness_query = is_unread or (query and any(kw in query.lower() for kw in freshness_keywords))
        
        # Relax parsing logic: If sender is a name (no @), try to resolve or fall back to keyword
        sender_logic_run = False
        if from_email:
             sender_logic_run = True
             if '@' not in from_email:
                # ALWAYS save original sender name for RAG result validation later
                self._original_sender_name = from_email
                
                # 1. Add to query keywords if not present
                if not query or from_email.lower() not in query.lower():
                    # If query is about charging/subscription/receipt, ensure those keywords are preserved
                    query = f"{query} {from_email}".strip() if query else from_email
                    
                # Explicitly add billing keywords if missing but search looks financial
                financial_keywords = ['charge', 'charged', 'subscription', 'receipt', 'invoice', 'payment', 'billing', 'price', 'cost']
                if query and any(kw in query.lower() for kw in financial_keywords):
                    if not any(kw in query.lower() for kw in ['receipt', 'invoice', 'bill', 'billing']):
                        query = f"{query} (receipt OR invoice OR bill OR billing OR stripe)".strip()
                
                logger.info(f"[EMAIL_SEARCH] Including entity '{from_email}' in keywords")
                
                # 2. Try to resolve to email address
                try:
                    resolved = self._resolve_name_to_emails_sync(from_email)
                    if resolved:
                        from_email = resolved[0]
                    else:
                        # 3. If no resolution, CLEAR from_email to avoid strict 'from:' filter
                        # This yields a global keyword search for the name (finding it in body/subject)
                        logger.info(f"[EMAIL_SEARCH] Could not resolve '{from_email}', relaxing to keyword search")
                        from_email = None
                except Exception as e:
                    logger.debug(f"[EMAIL_SEARCH] Name resolution failed during search logic: {e}")
                    from_email = None
 
        if query and not from_email and not sender_logic_run:
            try:
                from ..agent.parsers.email.sender_extractor import SenderExtractor
                class EmailParserWrapper:
                    def __init__(self, llm_client): self.llm_client = llm_client
                email_parser_wrapper = EmailParserWrapper(self.llm_client) if self.llm_client else None
                sender_extractor = SenderExtractor(email_parser=email_parser_wrapper)
                extracted_sender = sender_extractor.extract_sender(query)
                if extracted_sender:
                    # Logic mirrors above
                    temp_sender = extracted_sender
                    if '@' not in temp_sender:
                        # Add to query if needed
                        if not query or temp_sender.lower() not in query.lower():
                            query = f"{query} {temp_sender}".strip() if query else temp_sender
                        
                        try:
                            resolved_emails = self._resolve_name_to_emails_sync(temp_sender)
                            if resolved_emails:
                                self._original_sender_name = temp_sender
                                from_email = resolved_emails[0]
                            else:
                                # Don't set from_email, rely on keyword
                                logger.info(f"[EMAIL_SEARCH] Extracted '{temp_sender}' but could not resolve - using keyword")
                                from_email = None
                        except Exception as e:
                            logger.debug(f"[EMAIL_SEARCH] Name resolution failed: {e}")
                    else:
                        from_email = temp_sender
            except Exception as e:
                logger.debug(f"[EMAIL_SEARCH] Sender extraction failed: {e}")
        
        is_time_based_query = False
        newer_than_value = None
        if query and (not after_date and not before_date) and self.date_parser:
            try:
                parsed_date_range = self.date_parser.parse_date_expression(query, prefer_future=False)
                if parsed_date_range and 'start' in parsed_date_range:
                    start_dt = parsed_date_range['start']
                    end_dt = parsed_date_range.get('end', datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now())
                    duration = end_dt - start_dt
                    now_with_tz = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
                    time_from_now = abs((end_dt - now_with_tz).total_seconds()) if start_dt.tzinfo else abs((end_dt.replace(tzinfo=None) - now_with_tz.replace(tzinfo=None)).total_seconds())
                    if duration < timedelta(days=2) and time_from_now < 300:
                        total_seconds = int(duration.total_seconds())
                        if total_seconds < 3600: newer_than_value = f"{total_seconds // 60}m"
                        elif total_seconds < 86400: newer_than_value = f"{total_seconds // 3600}h"
                        else: newer_than_value = f"{total_seconds // 86400}d"
                        is_time_based_query = True
                    else:
                        after_date = start_dt.strftime("%Y/%m/%d")
                        # Add 1 day to end_dt for 'before:' filter because it's exclusive in Gmail
                        before_date = (end_dt + timedelta(days=1)).strftime("%Y/%m/%d")
            except Exception as e:
                logger.debug(f"[EMAIL_SEARCH] Date parsing failed: {e}")

        has_graph = self.hybrid_coordinator and hasattr(self.hybrid_coordinator, 'graph') and self.hybrid_coordinator.graph
        emails_from_index = []
        
        if from_email and has_graph and allow_rag:
            try:
                loop = asyncio.get_event_loop()
                graph_results = []
                # Simple helper to run async in thread
                def run_graph_query(f_email, a_date, b_date, sub, fold, unread, lim):
                    return asyncio.run(self._query_graph_for_emails(f_email, a_date, b_date, sub, fold, unread, lim))
                
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        graph_results = executor.submit(run_graph_query, from_email, after_date, before_date, subject, folder, is_unread, limit).result(timeout=5.0)
                else:
                    graph_results = loop.run_until_complete(self._query_graph_for_emails(from_email, after_date, before_date, subject, folder, is_unread, limit))
                
                if graph_results:
                    if not is_freshness_query: return graph_results[:limit]
                    emails_from_index = graph_results
            except Exception as e:
                logger.debug(f"[EMAIL_SEARCH] Graph failed: {e}")

        if self.hybrid_coordinator and not emails_from_index and allow_rag:
            try:
                # Hybrid search strategy
                # NOTE: With dedicated conversations collection, we no longer need type filtering here
                # The ConversationMemory now uses separate 'conversations' collection
                hybrid_filters = {'user_id': self.user_id} if self.user_id else {}
                if from_email: hybrid_filters['sender'] = from_email
                if subject: hybrid_filters['subject'] = subject
                
                # Always use asyncio.run() in a fresh thread to avoid event loop issues
                import concurrent.futures
                
                def run_hybrid_sync(use_graph_flag=True, filters=None):
                    """Run hybrid query in a new event loop (thread-safe)"""
                    return asyncio.run(self.hybrid_coordinator.query(
                        text_query=query or "email", 
                        use_graph=use_graph_flag, 
                        vector_limit=limit*2, 
                        filters=filters or {}
                    ))
                
                hybrid_result = {}
                # 1. Try Hybrid (Graph + Vector) with user_id filter
                # FIX: Relax filters for Qdrant (which uses strict MatchValue). 
                # Don't filter by subject/sender strictly unless we are sure.
                # Instead, ensure the query contains these terms.
                
                final_filters = {'user_id': self.user_id} if self.user_id else {}
                
                # Only filter by sender if it's a valid email (strict match safe)
                # If it's a name (e.g. "Eleven Labs"), strict match fails against "Eleven Labs Inc."
                if from_email and '@' in from_email:
                    final_filters['sender'] = from_email
                
                # Construct rich query (Subject + Query + Sender Name)
                rich_query = query
                
                # Append sender name to query if it's not an email address (for semantic matching)
                if from_email and '@' not in from_email:
                    if from_email.lower() not in rich_query.lower():
                        rich_query = f"{rich_query} from {from_email}"
                
                # Append subject to query (don't filter strictly as subject often varies)
                if subject:
                    if subject.lower() not in rich_query.lower():
                        rich_query = f"{rich_query} subject {subject}"

                logger.info(f"[EMAIL_SEARCH] Attempting Hybrid RAG search for: '{rich_query}' (Filters: {final_filters.keys()})")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_hybrid_sync, True, final_filters)
                    hybrid_result = future.result(timeout=10.0)
                
                # 2. Fallback to Pure Vector if Hybrid yielded nothing (Graph constraint might be too strict)
                if not hybrid_result.get('results'):
                    logger.info("[EMAIL_SEARCH] Hybrid search yielded 0 results, attempting Pure Vector RAG...")
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(run_hybrid_sync, False, hybrid_filters)
                        hybrid_result = future.result(timeout=10.0)
                
                # 3. Final fallback: Search WITHOUT user_id filter (handles user_id migration issues)
                if not hybrid_result.get('results') and self.user_id:
                    logger.info("[EMAIL_SEARCH] No results with user_id filter, retrying without user_id filter...")
                    relaxed_filters = {}  # No user_id filter
                    if from_email: relaxed_filters['sender'] = from_email
                    if subject: relaxed_filters['subject'] = subject
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(run_hybrid_sync, False, relaxed_filters)
                        hybrid_result = future.result(timeout=10.0)

                if hybrid_result.get('results'):
                    logger.info(f"[EMAIL_SEARCH] RAG found {len(hybrid_result.get('results'))} results")

                for item in hybrid_result.get('results', []):
                    meta = item.get('metadata', {})
                    emails_from_index.append({
                        'id': meta.get('email_id') or item.get('id', ''),
                        'subject': meta.get('subject', 'No Subject'),
                        'sender': meta.get('sender') or 'Unknown',
                        'from': meta.get('sender') or 'Unknown',
                        'date': meta.get('timestamp') or '',
                        'body': item.get('content', ''),
                        'snippet': item.get('content', '')[:200],
                        '_source': 'hybrid'
                    })
            except Exception as e:
                logger.warning(f"[EMAIL_SEARCH] Hybrid/RAG search failed: {e}")

        if emails_from_index and not is_freshness_query and len(emails_from_index) >= limit:
            # When specific filters were requested (sender/subject), verify RAG results
            # actually match before returning them. RAG returns semantically similar but
            # often irrelevant results that prevent Gmail API from being reached.
            has_specific_criteria = bool(subject or self._original_sender_name)
            
            if has_specific_criteria:
                matched = emails_from_index  # Start with all
                
                # Filter by subject if specified
                if subject:
                    subject_lower = subject.lower()
                    matched = [e for e in matched if subject_lower in (e.get('subject', '') or '').lower()]
                
                # Filter by sender name if specified
                if self._original_sender_name:
                    sender_lower = self._original_sender_name.lower()
                    # Check both 'sender' and 'from' fields
                    matched = [e for e in matched 
                               if sender_lower in (e.get('sender', '') or '').lower() 
                               or sender_lower in (e.get('from', '') or '').lower()]
                
                if matched:
                    return matched[:limit]
                else:
                    criteria = []
                    if subject: criteria.append(f"subject='{subject}'")
                    if self._original_sender_name: criteria.append(f"sender='{self._original_sender_name}'")
                    logger.info(f"[EMAIL_SEARCH] RAG returned {len(emails_from_index)} results but none match {', '.join(criteria)}, falling through to Gmail API")
                    emails_from_index = []  # Clear so Gmail API runs
            else:
                return emails_from_index[:limit]

        # Gmail API Fallback
        self._ensure_available()
        try:
            search_parts = []
            # Only add 'in:' filter if specific folder requested and NOT 'all'
            if folder and folder.lower() not in ['all', 'any']:
                search_parts.append(f"in:{folder}")
            
            if from_email:
                from_parts = []
                if '@' in from_email: 
                    from_parts.append(f'from:{from_email}')
                else: 
                    from_parts.append(f'from:({from_email})')
                
                # Also try the original name if resolution changed it significantly
                if self._original_sender_name and self._original_sender_name.lower() != (from_email or '').lower():
                    # Only add if not already contained
                    if self._original_sender_name.lower() not in (from_email or '').lower():
                        if '@' in self._original_sender_name:
                             from_parts.append(f'from:{self._original_sender_name}')
                        else:
                             from_parts.append(f'from:({self._original_sender_name})')
                
                if len(from_parts) > 1:
                    # Join multiple from filters with OR
                    search_parts.append(f"({' OR '.join(from_parts)})")
                else:
                    search_parts.append(from_parts[0])
            elif self._original_sender_name:
                # Name resolution failed but we still have the original sender name
                # Gmail can match sender display names with from:(name)
                search_parts.append(f'from:({self._original_sender_name})')
            
            if newer_than_value: 
                search_parts.append(f"newer_than:{newer_than_value}")
            else:
                if after_date: search_parts.append(f"after:{after_date}")
                if before_date: search_parts.append(f"before:{before_date}")
            
            if subject: 
                # Relaxed subject matching: use keywords instead of exact phrase
                # But wrap in parenthesis for safety if it contains spaces or operators
                search_parts.append(f'subject:({subject})')
            
            if is_unread is not None: 
                search_parts.append("is:unread" if is_unread else "is:read")
            
            if query:
                # When structured filters (from:/subject:) are present, the conversational
                # query text MUST be skipped entirely. Gmail requires ALL keywords to match,
                # so "from:(Sagar Agrawal) regarding scaling Clavr beta success" returns 0
                # results because Gmail looks for the literal words "regarding", "scaling" etc.
                # The from:/subject: filter alone is always sufficient.
                has_structured_filter = bool(subject or from_email or self._original_sender_name)
                
                if not has_structured_filter:
                    # No structured filters — clean up conversational words and use as keywords
                    junk_words = r'\b(find|search|show|emails|email|about|what|whats|what\'s|the|from|all|my|in|for|me|how|much|was|i|is|a|of|can|you|please|full|content|tell|give|get|more|details|regarding|read|note|message)\b'
                    clean_q = re.sub(junk_words, '', query, flags=re.IGNORECASE).strip()
                    clean_q = re.sub(r'[?.,!]', ' ', clean_q).strip()
                    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
                    
                    if clean_q: 
                        search_parts.append(clean_q)
            
            gmail_query = " ".join(search_parts)
            logger.info(f"[EMAIL_SEARCH] Gmail API query: '{gmail_query}' (folder={folder}, limit={limit})")
            results = self.gmail_client.search_emails(query=gmail_query, folder=folder, limit=limit)
            
            # If from: filter returned 0, retry with sender name as keyword instead
            if not results and self._original_sender_name and not from_email:
                keyword_query = self._original_sender_name
                if folder and folder.lower() not in ['all', 'any']:
                    keyword_query = f"in:{folder} {keyword_query}"
                logger.info(f"[EMAIL_SEARCH] Retrying Gmail with keyword fallback: '{keyword_query}'")
                results = self.gmail_client.search_emails(query=keyword_query, folder='all', limit=limit)
            
            if emails_from_index:
                seen = {e['id'] for e in emails_from_index}
                for res in results:
                    if res['id'] not in seen:
                        res['_source'] = 'gmail_api'
                        emails_from_index.append(res)
                emails_from_index.sort(key=lambda x: x.get('date', ''), reverse=True)
                return emails_from_index[:limit]
            
            # If Gmail API returned results, return them
            if results:
                return results
            
            # === RAG SEMANTIC SEARCH FALLBACK ===
            # Gmail API searches email bodies but NOT attachment content (PDFs, etc.)
            # If no results, query the RAG vector store which contains indexed attachment text.
            if query and self.rag_engine and allow_rag:
                logger.info(f"[EMAIL_SEARCH] Gmail API returned 0 results, attempting RAG semantic search...")
                try:
                    import concurrent.futures
                    
                    # NOTE: With dedicated conversations collection, type filtering is no longer needed
                    
                    def run_semantic_search_sync():
                        """Run semantic search in a new event loop (thread-safe)"""
                        return asyncio.run(self.semantic_search(query=query, limit=limit))
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(run_semantic_search_sync)
                        rag_results = future.result(timeout=10.0)
                    
                    if rag_results:
                        logger.info(f"[EMAIL_SEARCH] RAG semantic search found {len(rag_results)} results")
                        
                        # Validate against sender/subject criteria (same as initial RAG check)
                        if self._original_sender_name or subject:
                            validated = rag_results
                            if subject:
                                subject_lower = subject.lower()
                                validated = [e for e in validated if subject_lower in (e.get('subject', '') or '').lower()]
                            if self._original_sender_name:
                                sender_lower = self._original_sender_name.lower()
                                validated = [e for e in validated
                                             if sender_lower in (e.get('sender', '') or '').lower()
                                             or sender_lower in (e.get('from', '') or '').lower()]
                            if validated:
                                for r in validated:
                                    r['_source'] = 'rag_semantic'
                                return validated[:limit]
                            else:
                                logger.info(f"[EMAIL_SEARCH] RAG semantic fallback: {len(rag_results)} results but none match sender/subject criteria")
                                return []
                        
                        for r in rag_results:
                            r['_source'] = 'rag_semantic'
                        return rag_results[:limit]
                except Exception as e:
                    logger.warning(f"[EMAIL_SEARCH] RAG semantic fallback failed: {e}")
            
            return []
        except Exception as e:
            logger.error(f"[EMAIL_SEARCH] Gmail search failed: {e}")
            raise EmailSearchException(f"Search failed: {e}", service_name="email")

    def list_unread_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.search_emails(is_unread=True, limit=limit)
    
    def list_recent_emails(self, limit: int = 10, folder: str = "inbox") -> List[Dict[str, Any]]:
        return self.search_emails(folder=folder, limit=limit)

    async def get_unread_count(self) -> int:
        self._ensure_available()
        try:
            if self.hybrid_coordinator and self.hybrid_coordinator.graph:
                aql = "RETURN LENGTH(FOR e IN Email FILTER e.user_id == @user_id AND e.is_unread == true RETURN 1)"
                res = await self.hybrid_coordinator.graph.execute_query(aql, {"user_id": self.user_id})
                if res: return int(res[0])
            return self.gmail_client.get_unread_count()
        except Exception as e:
            logger.debug(f"[EMAIL_SEARCH] Unread count query failed: {e}")
            return 0

    async def semantic_search(self, query: str, limit: int = 10, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self.rag_engine: return []
        try:
            if self.user_id:
                filters = filters or {}
                filters['user_id'] = self.user_id
            results = await asyncio.to_thread(self.rag_engine.search, query=query, k=limit, filters=filters)
            return [{'id': r.get('metadata', {}).get('email_id'), 'subject': r.get('metadata', {}).get('subject'), 'body': r.get('content'), 'snippet': r.get('content')[:200]} for r in results]
        except Exception as e:
            logger.debug(f"[EMAIL_SEARCH] Semantic search failed: {e}")
            return []
