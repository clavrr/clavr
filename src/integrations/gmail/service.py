"""
Email Service - Business logic layer for email operations

Provides a clean interface for email operations, abstracting away the complexity
of Gmail API, credential management, and error handling.

This service is used by:
- EmailTool (LangChain tool)
- Email background workers (Celery tasks)
- API endpoints

Architecture:
    EmailService → GoogleGmailClient → Gmail API
    EmailService → RAGEngine (optional, for semantic search)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import re
import asyncio

from ...core.email.google_client import GoogleGmailClient
from ...utils.logger import setup_logger
from ...utils.config import Config
from .exceptions import (
    EmailServiceException,
    EmailNotFoundException,
    EmailSendException,
    EmailSearchException,
    ServiceUnavailableException
)

logger = setup_logger(__name__)


class EmailService:
    """
    Email service providing business logic for email operations
    
    Features:
    - Send and reply to emails
    - Search and filter emails
    - Bulk operations (archive, delete, mark)
    - Email categorization and organization
    - Analytics and insights
    - RAG integration for semantic search
    """
    
    def __init__(
        self,
        config: Config,
        credentials: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        hybrid_coordinator: Optional[Any] = None
    ):
        """
        Initialize email service
        
        Args:
            config: Application configuration
            credentials: OAuth credentials (if available)
            rag_engine: RAG engine for semantic search (optional)
            hybrid_coordinator: Hybrid index coordinator for graph+vector queries (optional)
        """
        self.config = config
        self.credentials = credentials
        self.rag_engine = rag_engine
        self.hybrid_coordinator = hybrid_coordinator
        
        # Initialize intelligent parsers (FlexibleDateParser and LLM for sender extraction)
        self.date_parser = None
        self.llm_client = None
        
        try:
            from ..utils import FlexibleDateParser
            self.date_parser = FlexibleDateParser(config)
            logger.debug("[EMAIL_SERVICE] FlexibleDateParser initialized")
        except Exception as e:
            logger.debug(f"[EMAIL_SERVICE] FlexibleDateParser not available: {e}")
        
        # Initialize LLM client for intelligent sender extraction (optional)
        try:
            from ..ai.llm_factory import LLMFactory
            self.llm_client = LLMFactory.get_llm_for_provider(config, temperature=0.1)
            logger.debug("[EMAIL_SERVICE] LLM client initialized for intelligent extraction")
        except Exception as e:
            logger.debug(f"[EMAIL_SERVICE] LLM client not available (will use pattern fallback): {e}")
        
        # Initialize Gmail client
        try:
            self.gmail_client = GoogleGmailClient(config, credentials=credentials)
            if not self.gmail_client.is_available():
                logger.warning("[EMAIL_SERVICE] Gmail client not available")
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to initialize Gmail client: {e}")
            self.gmail_client = None
    
    async def _query_neo4j_for_emails(
        self,
        from_email: Optional[str] = None,
        after_date: Optional[str] = None,
        before_date: Optional[str] = None,
        subject: Optional[str] = None,
        folder: str = "inbox",
        is_unread: Optional[bool] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Query Neo4j graph database for emails using structured filters.
        This is MUCH more accurate than Pinecone semantic search + post-filtering.
        
        Args:
            from_email: Sender email/name filter
            after_date: Date filter (YYYY/MM/DD format)
            before_date: Date filter (YYYY/MM/DD format)
            subject: Subject filter
            folder: Folder/label filter
            is_unread: Unread status filter
            limit: Maximum results
            
        Returns:
            List of email dictionaries
        """
        if not self.hybrid_coordinator or not self.hybrid_coordinator.graph:
            logger.debug("[EMAIL_SERVICE] Neo4j not available for query")
            return []
        
        try:
            graph = self.hybrid_coordinator.graph
            
            # First, check if any emails exist in Neo4j (diagnostic query)
            try:
                test_query = "MATCH (e:Email) RETURN count(e) as total"
                test_results = await graph.query(test_query, params={})
                if test_results and len(test_results) > 0:
                    total_count = test_results[0].get('total', 0) if isinstance(test_results[0], dict) else 0
                    logger.info(f"[EMAIL_SERVICE] Neo4j diagnostic: Found {total_count} total Email nodes in graph")
                else:
                    logger.warning("[EMAIL_SERVICE] Neo4j diagnostic: No Email nodes found in graph (emails may not be indexed yet)")
                
                # If we have a sender filter, check what sender values actually exist that might match
                if from_email:
                    from_email_lower = from_email.lower()
                    # Query to find senders that contain the search term (using parameters for safety)
                    sender_diag_query = """
                        MATCH (e:Email)
                        WHERE toLower(e.sender) CONTAINS $from_email
                           OR split(toLower(e.sender), '@')[0] CONTAINS $from_email
                        RETURN DISTINCT e.sender as sender, count(e) as count
                        ORDER BY count DESC
                        LIMIT 10
                    """
                    try:
                        sender_results = await graph.query(sender_diag_query, params={'from_email': from_email_lower})
                        if sender_results and len(sender_results) > 0:
                            logger.info(f"[EMAIL_SERVICE] Neo4j diagnostic: Found {len(sender_results)} sender(s) matching '{from_email}':")
                            for idx, result in enumerate(sender_results[:5], 1):
                                # Handle Neo4j result format
                                if isinstance(result, dict):
                                    sender_val = result.get('sender', 'N/A')
                                    count = result.get('count', 0)
                                else:
                                    sender_val = 'N/A'
                                    count = 0
                                logger.info(f"[EMAIL_SERVICE]   [{idx}] sender='{sender_val}', count={count}")
                        else:
                            logger.warning(f"[EMAIL_SERVICE] Neo4j diagnostic: No senders found matching '{from_email}' - checking sample senders...")
                            # Get sample senders to see what format they're in
                            sample_query = "MATCH (e:Email) RETURN DISTINCT e.sender as sender LIMIT 10"
                            sample_results = await graph.query(sample_query, params={})
                            if sample_results:
                                logger.info(f"[EMAIL_SERVICE] Sample sender formats in Neo4j:")
                                for idx, result in enumerate(sample_results[:5], 1):
                                    if isinstance(result, dict):
                                        sender_val = result.get('sender', 'N/A')
                                    else:
                                        sender_val = 'N/A'
                                    logger.info(f"[EMAIL_SERVICE]   [{idx}] sender='{sender_val}'")
                            
                            # Check if ANY emails exist from the date range (to verify date filtering works)
                            if after_date or before_date:
                                date_check_query = """
                                    MATCH (e:Email)
                                    WHERE (e.date >= $after_date OR e.timestamp >= $after_date_ts)
                                      AND (e.date < $before_date OR e.timestamp < $before_date_ts)
                                    RETURN count(e) as count
                                """
                                date_params = {}
                                if after_date:
                                    after_date_neo4j = after_date.replace('/', '-')
                                    date_params['after_date'] = after_date_neo4j
                                    date_params['after_date_ts'] = f"{after_date_neo4j}T00:00:00"
                                if before_date:
                                    before_date_neo4j = before_date.replace('/', '-')
                                    date_params['before_date'] = before_date_neo4j
                                    date_params['before_date_ts'] = f"{before_date_neo4j}T23:59:59"
                                
                                try:
                                    date_results = await graph.query(date_check_query, params=date_params)
                                    if date_results and len(date_results) > 0:
                                        date_count = date_results[0].get('count', 0) if isinstance(date_results[0], dict) else 0
                                        logger.info(f"[EMAIL_SERVICE] Neo4j diagnostic: Found {date_count} emails in date range ({after_date} to {before_date})")
                                    else:
                                        logger.warning(f"[EMAIL_SERVICE] Neo4j diagnostic: No emails found in date range ({after_date} to {before_date})")
                                except Exception as date_check_e:
                                    logger.debug(f"[EMAIL_SERVICE] Date check query failed: {date_check_e}")
                    except Exception as sender_diag_e:
                        logger.debug(f"[EMAIL_SERVICE] Sender diagnostic query failed: {sender_diag_e}", exc_info=True)
            except Exception as diag_e:
                logger.debug(f"[EMAIL_SERVICE] Neo4j diagnostic query failed: {diag_e}")
            
            # Build Cypher query with filters
            where_clauses = []
            params = {}
            
            # Filter by sender (exact match on email or name)
            if from_email:
                # Try to match email address or name parts
                # Neo4j stores sender as email address in Email nodes
                # Use case-insensitive matching and handle partial names like "Alvaro" matching "alvaro.santana-acuna@domain.com"
                from_email_lower = from_email.lower()
                # Match if sender equals query, contains query, or query is in sender email local part (before @)
                where_clauses.append("""
                    (toLower(e.sender) = $from_email 
                     OR toLower(e.sender) CONTAINS $from_email 
                     OR split(toLower(e.sender), '@')[0] CONTAINS $from_email
                     OR any(part IN split($from_email, ' ') WHERE toLower(e.sender) CONTAINS part AND size(part) > 2))
                """.strip())
                params['from_email'] = from_email_lower
            
            # Filter by date - handle both date (YYYY-MM-DD) and timestamp (ISO) properties
            if after_date:
                # Convert YYYY/MM/DD to YYYY-MM-DD for Neo4j
                after_date_neo4j = after_date.replace('/', '-')
                # Try both date property (YYYY-MM-DD) and timestamp property (ISO datetime)
                where_clauses.append(f"(e.date >= '{after_date_neo4j}' OR e.timestamp >= '{after_date_neo4j}T00:00:00')")
            
            if before_date:
                before_date_neo4j = before_date.replace('/', '-')
                # Try both date property (YYYY-MM-DD) and timestamp property (ISO datetime)
                where_clauses.append(f"(e.date < '{before_date_neo4j}' OR e.timestamp < '{before_date_neo4j}T23:59:59')")
            
            # Filter by subject
            if subject:
                where_clauses.append("e.subject CONTAINS $subject")
                params['subject'] = subject
            
            # Filter by folder
            if folder and folder != 'inbox':
                where_clauses.append("e.folder = $folder")
                params['folder'] = folder
            
            # Filter by unread status
            if is_unread is not None:
                where_clauses.append("e.is_unread = $is_unread")
                params['is_unread'] = is_unread
            
            # Build query
            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
            cypher_query = f"""
                MATCH (e:Email)
                WHERE {where_clause}
                RETURN e
                ORDER BY e.timestamp DESC, e.date DESC
                LIMIT $limit
            """
            params['limit'] = limit
            
            logger.info(f"[EMAIL_SERVICE] Neo4j query: {cypher_query}")
            logger.info(f"[EMAIL_SERVICE] Neo4j query params: {params}")
            
            # Execute query
            results = await graph.query(cypher_query, params=params)
            
            logger.info(f"[EMAIL_SERVICE] Neo4j query returned {len(results)} results")
            
            # Convert Neo4j results to EmailService format
            emails = []
            for idx, result in enumerate(results):
                logger.debug(f"[EMAIL_SERVICE] Neo4j result {idx}: type={type(result)}, keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                if 'e' in result:
                    node_data = result['e']
                    
                    # Handle Neo4j Node objects - they can be accessed like dicts but aren't actually dicts
                    # Try to extract properties in multiple ways
                    props = {}
                    if hasattr(node_data, 'get'):
                        # Node object with get method (Neo4j Node)
                        if hasattr(node_data, 'properties'):
                            props = node_data.properties
                        else:
                            # Try accessing as dict
                            props = dict(node_data) if hasattr(node_data, '__iter__') else {}
                    elif isinstance(node_data, dict):
                        # Already a dict
                        props = node_data.get('properties', node_data) if isinstance(node_data.get('properties'), dict) else node_data
                    else:
                        logger.warning(f"[EMAIL_SERVICE] Unexpected node_data type: {type(node_data)}")
                        continue
                        
                    # CRITICAL: Use full body content from Neo4j, not just snippet
                    full_body = props.get('body', '') or ''
                    email_data = {
                        'id': props.get('email_id') or props.get('id', ''),
                        'threadId': props.get('thread_id', ''),
                        'subject': props.get('subject', 'No Subject'),
                        'sender': props.get('sender', 'Unknown'),
                        'from': props.get('sender', 'Unknown'),
                        'date': props.get('timestamp') or props.get('date', ''),
                        'snippet': full_body[:200] if full_body else '',  # Keep snippet for backward compatibility
                        'body': full_body,  # CRITICAL: Include full body content from Neo4j
                        'labels': props.get('labels', []),
                        'has_attachments': props.get('has_attachments', False),
                        'folder': props.get('folder', folder),
                        '_source': 'neo4j'
                    }
                    logger.debug(f"[EMAIL_SERVICE] Extracted email: sender='{email_data['sender']}', date='{email_data['date']}', subject='{email_data['subject'][:50]}'")
                    emails.append(email_data)
                else:
                    logger.warning(f"[EMAIL_SERVICE] Result {idx} missing 'e' key: {result}")
            
            return emails
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Neo4j query failed: {e}", exc_info=True)
            return []
    
    def _ensure_available(self):
        """Ensure Gmail client is available"""
        if not self.gmail_client or not self.gmail_client.is_available():
            raise ServiceUnavailableException(
                "Gmail service is not available. Please authenticate.",
                service_name="email"
            )
    
    # ===================================================================
    # CORE EMAIL OPERATIONS
    # ===================================================================
    
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send a new email
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            cc: CC recipients (optional)
            bcc: BCC recipients (optional)
            attachments: List of attachments (optional)
            
        Returns:
            Sent email details
            
        Raises:
            EmailSendException: If sending fails
        """
        self._ensure_available()
        
        try:
            logger.info(f"[EMAIL_SERVICE] Sending email to {to}: {subject}")
            
            result = self.gmail_client.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                attachments=attachments
            )
            
            logger.info(f"[EMAIL_SERVICE] Email sent successfully")
            return result
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to send email: {e}")
            raise EmailSendException(
                f"Failed to send email: {str(e)}",
                service_name="email",
                details={'to': to, 'subject': subject}
            )
    
    def reply_to_email(
        self,
        message_id: str,
        body: str,
        cc: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Reply to an existing email
        
        Args:
            message_id: ID of message to reply to
            body: Reply body text
            cc: Additional CC recipients (optional)
            
        Returns:
            Sent reply details
            
        Raises:
            EmailNotFoundException: If original email not found
            EmailSendException: If reply fails
        """
        self._ensure_available()
        
        try:
            logger.info(f"[EMAIL_SERVICE] Replying to email {message_id}")
            
            result = self.gmail_client.reply_to_email(
                message_id=message_id,
                body=body,
                cc=cc
            )
            
            logger.info(f"[EMAIL_SERVICE] Reply sent successfully")
            return result
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to reply to email: {e}")
            raise EmailSendException(
                f"Failed to reply to email: {str(e)}",
                service_name="email",
                details={'message_id': message_id}
            )
    
    def get_email(
        self,
        message_id: str
    ) -> Dict[str, Any]:
        """
        Get a single email by ID
        
        Args:
            message_id: Email message ID
            
        Returns:
            Email details
            
        Raises:
            EmailNotFoundException: If email not found
        """
        self._ensure_available()
        
        try:
            email = self.gmail_client.get_message(message_id)
            
            if not email:
                raise EmailNotFoundException(
                    f"Email {message_id} not found",
                    service_name="email"
                )
            
            return email
            
        except EmailNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to get email: {e}")
            raise EmailServiceException(
                f"Failed to get email: {str(e)}",
                service_name="email",
                details={'message_id': message_id}
            )
    
    # ===================================================================
    # SEARCH AND LISTING
    # ===================================================================
    
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
        is_unread: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        Search emails with filters - OPTIMIZED: Uses index first, falls back to Gmail API
        
        This method now:
        1. First queries the RAG/index for fast retrieval
        2. Falls back to Gmail API only if:
           - Index doesn't have enough results
           - Query requires very recent emails (< 5 minutes old)
           - Index is unavailable
        
        Args:
            query: Search query text
            folder: Gmail folder/label
            limit: Maximum number of results
            from_email: Filter by sender
            to_email: Filter by recipient
            subject: Filter by subject
            has_attachment: Filter by attachment presence
            after_date: Filter by date (after)
            before_date: Filter by date (before)
            is_unread: Filter by unread status
            
        Returns:
            List of matching emails
            
        Raises:
            EmailSearchException: If search fails
        """
        # Extract sender from query using intelligent sender extractor with LLM support (no hardcoded patterns)
        if query and not from_email:
            try:
                # Use intelligent sender extractor with LLM support
                from ..agent.parsers.email.sender_extractor import SenderExtractor
                # Create a minimal email parser wrapper for LLM support if available
                email_parser_wrapper = None
                if self.llm_client:
                    class EmailParserWrapper:
                        def __init__(self, llm_client):
                            self.llm_client = llm_client
                    email_parser_wrapper = EmailParserWrapper(self.llm_client)
                
                sender_extractor = SenderExtractor(email_parser=email_parser_wrapper)
                extracted_sender = sender_extractor.extract_sender(query)
                
                if extracted_sender:
                    from_email = extracted_sender
                    logger.info(f"[EMAIL_SERVICE] Intelligent sender extractor found: '{from_email}'")
            except Exception as e:
                logger.debug(f"[EMAIL_SERVICE] Sender extractor failed, query will be used as-is: {e}")
                # Fallback: query will be used for semantic search without explicit sender filter
        
        # Extract date/time from query using intelligent FlexibleDateParser (no hardcoded patterns)
        # Track if this is a time-based query (hours/minutes) vs date-based query
        is_time_based_query = False
        newer_than_value = None
        
        if query and (not after_date and not before_date) and self.date_parser:
            try:
                # Use FlexibleDateParser to intelligently parse temporal references from query
                # This handles: "yesterday", "today", "2 days ago", "last week", "November 19", "past hour", etc.
                parsed_date_range = self.date_parser.parse_date_expression(query, prefer_future=False)
                
                if parsed_date_range and 'start' in parsed_date_range and 'end' in parsed_date_range:
                    start_dt = parsed_date_range['start']
                    end_dt = parsed_date_range['end']
                    
                    # Check if this is a time-based query (hours/minutes) vs date-based
                    # Time-based queries have duration < 2 days and end at "now"
                    from datetime import datetime, timedelta
                    duration = end_dt - start_dt
                    # Check if end_dt is close to now (within 5 minutes)
                    now_with_tz = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
                    if start_dt.tzinfo and not now_with_tz.tzinfo:
                        import pytz
                        now_with_tz = pytz.UTC.localize(now_with_tz) if not now_with_tz.tzinfo else now_with_tz
                    time_from_now = abs((end_dt - now_with_tz).total_seconds()) if start_dt.tzinfo else abs((end_dt.replace(tzinfo=None) - now_with_tz.replace(tzinfo=None)).total_seconds())
                    is_time_based = duration < timedelta(days=2) and time_from_now < 300  # Within 5 minutes of now
                    
                    if is_time_based:
                        # Convert to Gmail's newer_than format (supports: 1h, 30m, 1d, etc.)
                        total_seconds = int(duration.total_seconds())
                        if total_seconds < 3600:  # Less than 1 hour
                            newer_than_value = f"{total_seconds // 60}m"  # Minutes
                        elif total_seconds < 86400:  # Less than 1 day
                            newer_than_value = f"{total_seconds // 3600}h"  # Hours
                        else:
                            newer_than_value = f"{total_seconds // 86400}d"  # Days
                        
                        is_time_based_query = True
                        logger.info(f"[EMAIL_SERVICE] FlexibleDateParser detected time-based query: newer_than={newer_than_value} (duration: {duration})")
                    else:
                        # Date-based query - convert to Gmail date format
                        import pytz
                        utc_tz = pytz.UTC
                        
                        # Ensure timezone-aware
                        if start_dt.tzinfo is None:
                            from ..utils.config import get_timezone
                            from ..core.calendar.utils import get_user_timezone
                            tz_name = get_user_timezone(self.config) if self.config else get_timezone(self.config) or 'UTC'
                            user_tz = pytz.timezone(tz_name)
                            start_dt = user_tz.localize(start_dt) if start_dt.tzinfo is None else start_dt
                        
                        if end_dt.tzinfo is None:
                            from ..utils.config import get_timezone
                            from ..core.calendar.utils import get_user_timezone
                            tz_name = get_user_timezone(self.config) if self.config else get_timezone(self.config) or 'UTC'
                            user_tz = pytz.timezone(tz_name)
                            end_dt = user_tz.localize(end_dt) if end_dt.tzinfo is None else end_dt
                    
                    # Convert to UTC
                    start_utc = start_dt.astimezone(utc_tz)
                    end_utc = end_dt.astimezone(utc_tz)
                    
                    # Format as Gmail API date format (YYYY/MM/DD)
                    after_date = start_utc.strftime("%Y/%m/%d")
                    before_date = end_utc.strftime("%Y/%m/%d")
                    
                    logger.info(f"[EMAIL_SERVICE] FlexibleDateParser extracted date range from query: after:{after_date} before:{before_date} (start: {start_utc}, end: {end_utc})")
            except Exception as e:
                logger.debug(f"[EMAIL_SERVICE] FlexibleDateParser failed to extract date from query '{query}': {e}")
                # Continue without date filter if parsing fails
        
        # CRITICAL FIX: When we have a sender filter, use Neo4j graph search FIRST
        # Vector search is semantic and doesn't respect sender filters - it finds semantically similar emails
        # Neo4j can do exact/partial sender matching, which is what we need
        # CRITICAL: Check Neo4j availability FIRST before any other search
        has_neo4j = False
        if self.hybrid_coordinator:
            if hasattr(self.hybrid_coordinator, 'graph') and self.hybrid_coordinator.graph:
                has_neo4j = True
            else:
                logger.debug(f"[EMAIL_SERVICE] Neo4j check: hybrid_coordinator exists but graph is {getattr(self.hybrid_coordinator, 'graph', 'missing')}")
        else:
            logger.debug(f"[EMAIL_SERVICE] Neo4j check: hybrid_coordinator is {self.hybrid_coordinator}")
        
        logger.info(f"[EMAIL_SERVICE] DEBUG: Neo4j availability check - from_email={from_email}, has_hybrid_coordinator={bool(self.hybrid_coordinator)}, has_neo4j={has_neo4j}")
        
        # CRITICAL FIX: When we have a sender filter, use Neo4j graph search FIRST
        # Vector search is semantic and doesn't respect sender filters - it finds semantically similar emails
        # Neo4j can do exact/partial sender matching, which is what we need
        if from_email and has_neo4j:
            try:
                logger.info(f"[EMAIL_SERVICE] Sender filter present - using Neo4j graph search FIRST for accurate sender matching: from_email='{from_email}'")
                
                # Use Neo4j to find emails by sender (exact/partial match)
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None
                
                neo4j_results = []
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            lambda: asyncio.run(
                                self._query_neo4j_for_emails(
                                    from_email=from_email,
                                    after_date=after_date,
                                    before_date=before_date,
                                    subject=subject,
                                    folder=folder,
                                    is_unread=is_unread,
                                    limit=limit
                                )
                            )
                        )
                        neo4j_results = future.result(timeout=5.0)
                else:
                    if loop:
                        neo4j_results = loop.run_until_complete(
                            self._query_neo4j_for_emails(
                                from_email=from_email,
                                after_date=after_date,
                                before_date=before_date,
                                subject=subject,
                                folder=folder,
                                is_unread=is_unread,
                                limit=limit
                            )
                        )
                    else:
                        neo4j_results = asyncio.run(
                            self._query_neo4j_for_emails(
                                from_email=from_email,
                                after_date=after_date,
                                before_date=before_date,
                                subject=subject,
                                folder=folder,
                                is_unread=is_unread,
                                limit=limit
                            )
                        )
                
                if neo4j_results and len(neo4j_results) > 0:
                    logger.info(f"[EMAIL_SERVICE] ✓ Neo4j graph search found {len(neo4j_results)} emails matching sender '{from_email}'")
                    return neo4j_results[:limit]
                else:
                    logger.info(f"[EMAIL_SERVICE] Neo4j graph search found 0 emails for sender '{from_email}' with date filters")
                    # Try without date filters to see if sender matching works at all
                    try:
                        logger.debug(f"[EMAIL_SERVICE] Trying Neo4j query without date filters for sender '{from_email}'")
                        neo4j_results_no_date = []
                        if loop and loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(
                                    lambda: asyncio.run(
                                        self._query_neo4j_for_emails(
                                            from_email=from_email,
                                            after_date=None,
                                            before_date=None,
                                            subject=subject,
                                            folder=folder,
                                            is_unread=is_unread,
                                            limit=limit
                                        )
                                    )
                                )
                                neo4j_results_no_date = future.result(timeout=5.0)
                        else:
                            if loop:
                                neo4j_results_no_date = loop.run_until_complete(
                                    self._query_neo4j_for_emails(
                                        from_email=from_email,
                                        after_date=None,
                                        before_date=None,
                                        subject=subject,
                                        folder=folder,
                                        is_unread=is_unread,
                                        limit=limit
                                    )
                                )
                            else:
                                neo4j_results_no_date = asyncio.run(
                                    self._query_neo4j_for_emails(
                                        from_email=from_email,
                                        after_date=None,
                                        before_date=None,
                                        subject=subject,
                                        folder=folder,
                                        is_unread=is_unread,
                                        limit=limit
                                    )
                                )
                        
                        if neo4j_results_no_date and len(neo4j_results_no_date) > 0:
                            logger.info(f"[EMAIL_SERVICE] Found {len(neo4j_results_no_date)} emails from '{from_email}' without date filters (date filter may be too restrictive)")
                            # Filter by date in Python since Neo4j query didn't work
                            filtered_results = []
                            for email in neo4j_results_no_date:
                                email_date = email.get('date', '')
                                if after_date and email_date < after_date.replace('/', '-'):
                                    continue
                                if before_date and email_date >= before_date.replace('/', '-'):
                                    continue
                                filtered_results.append(email)
                            
                            if filtered_results:
                                logger.info(f"[EMAIL_SERVICE] After Python date filtering: {len(filtered_results)} emails match")
                                return filtered_results[:limit]
                            else:
                                logger.info(f"[EMAIL_SERVICE] All {len(neo4j_results_no_date)} emails from '{from_email}' were filtered out by date range")
                        else:
                            logger.info(f"[EMAIL_SERVICE] Neo4j found 0 emails for sender '{from_email}' even without date filters (email may not be indexed in Neo4j)")
                    except Exception as fallback_e:
                        logger.debug(f"[EMAIL_SERVICE] Fallback Neo4j query failed: {fallback_e}")
                    
                    logger.info(f"[EMAIL_SERVICE] Falling back to vector search")
            except Exception as e:
                logger.warning(f"[EMAIL_SERVICE] Neo4j graph search failed: {e}, falling back to vector search", exc_info=True)
        else:
            # No Neo4j available - log why
            if from_email:
                logger.info(f"[EMAIL_SERVICE] Neo4j not available for sender filter, will use vector search (hybrid_coordinator={bool(self.hybrid_coordinator)}, has_graph={hasattr(self.hybrid_coordinator, 'graph') if self.hybrid_coordinator else False})")
        
        # Try hybrid index-first approach following the architecture's two-step retrieval flow:
        # Step 1: Pinecone semantic search → Extract node_ids from metadata
        # Step 2: Neo4j graph traversal → Use node_ids to find related entities
        # 
        # For structured queries (sender, date filters), we can also use direct Neo4j queries
        # as an optimization, but the architecture pattern should be used for semantic queries.
        # NOTE: If we already tried Neo4j above for sender filter, skip this section to avoid duplicate work
        neo4j_already_checked = from_email and has_neo4j
        
        # CRITICAL: Validate hybrid_coordinator exists and has required methods before using it
        hybrid_coordinator_available = (
            self.hybrid_coordinator is not None and
            hasattr(self.hybrid_coordinator, 'query') and
            callable(getattr(self.hybrid_coordinator, 'query', None)) and
            hasattr(self.hybrid_coordinator, 'graph') and
            self.hybrid_coordinator.graph is not None
        )
        
        if hybrid_coordinator_available and not neo4j_already_checked:
            try:
                logger.info(f"[EMAIL_SERVICE] Attempting hybrid search (following architecture two-step flow): query='{query}', from_email='{from_email}', after_date='{after_date}', before_date='{before_date}'")
                
                # Determine query strategy based on filters
                has_structured_filters = from_email or after_date or before_date or subject
                has_semantic_query = query and len(query.strip()) > 5  # Meaningful text query
                
                # Strategy A: Use HybridIndexCoordinator.query() for semantic queries (follows architecture pattern)
                # This implements: Pinecone → extract node_ids → Neo4j traversal
                hybrid_results = []
                if has_semantic_query:
                    try:
                        # Build filters for hybrid coordinator
                        hybrid_filters = {}
                        if from_email:
                            hybrid_filters['sender'] = from_email
                        if subject:
                            hybrid_filters['subject'] = subject
                        if folder and folder != 'inbox':
                            hybrid_filters['folder'] = folder
                        if is_unread is not None:
                            hybrid_filters['is_unread'] = is_unread
                        if after_date:
                            hybrid_filters['date'] = {"$gte": after_date.replace('/', '-')}
                        if before_date:
                            if 'date' in hybrid_filters:
                                hybrid_filters['date']["$lte"] = before_date.replace('/', '-')
                            else:
                                hybrid_filters['date'] = {"$lte": before_date.replace('/', '-')}
                        
                        # Use HybridIndexCoordinator.query() - implements the two-step flow
                        # Step 1: Pinecone semantic search → Step 2: Neo4j graph traversal
                        loop = None
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        if loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(
                                    lambda: asyncio.run(
                                        self.hybrid_coordinator.query(
                                            text_query=query or "email",
                                            use_graph=True,
                                            use_vector=True,
                                            vector_limit=limit * 2,
                                            filters=hybrid_filters if hybrid_filters else None
                                        )
                                    )
                                )
                                hybrid_result = future.result(timeout=10.0)
                        else:
                            hybrid_result = loop.run_until_complete(
                                self.hybrid_coordinator.query(
                                    text_query=query or "email",
                                    use_graph=True,
                                    use_vector=True,
                                    vector_limit=limit * 2,
                                    filters=hybrid_filters if hybrid_filters else None
                                )
                            )
                        
                        # Validate hybrid_result is a dict with expected structure
                        if not isinstance(hybrid_result, dict):
                            logger.warning(f"[EMAIL_SERVICE] Hybrid query returned unexpected type: {type(hybrid_result)}, expected dict")
                            hybrid_result = {'results': []}
                        elif 'results' not in hybrid_result:
                            logger.warning(f"[EMAIL_SERVICE] Hybrid query result missing 'results' key, adding empty list")
                            hybrid_result['results'] = []
                        
                        # Extract emails from hybrid results
                        # Results follow architecture: Pinecone results enriched with Neo4j graph context
                        for result_item in hybrid_result.get('results', []):
                            metadata = result_item.get('metadata', {})
                            graph_context = result_item.get('graph_context')
                            
                            # Extract email data from metadata or graph context
                            if graph_context:
                                # Use graph node data (from Neo4j traversal)
                                node_data = graph_context.get('node', {})
                                props = node_data.get('properties', node_data) if isinstance(node_data.get('properties'), dict) else node_data
                                
                                # CRITICAL: Use full content from index, not just snippet
                                full_content = result_item.get('content', '') or ''
                                email_data = {
                                    'id': props.get('email_id') or props.get('id', ''),
                                    'threadId': props.get('thread_id', ''),
                                    'subject': props.get('subject', 'No Subject'),
                                    'sender': props.get('sender', 'Unknown'),
                                    'from': props.get('sender', 'Unknown'),
                                    'date': props.get('timestamp') or props.get('date', ''),
                                    'snippet': full_content[:200],  # Keep snippet for backward compatibility
                                    'body': full_content,  # CRITICAL: Include full body content from index
                                    'labels': props.get('labels', []),
                                    'has_attachments': props.get('has_attachments', False),
                                    'folder': props.get('folder', folder),
                                    '_source': 'hybrid_graphrag'  # Mark as from architecture pattern
                                }
                                hybrid_results.append(email_data)
                            elif metadata:
                                # Use Pinecone metadata (from Step 1)
                                email_id = metadata.get('email_id') or metadata.get('message_id') or metadata.get('id', '')
                                if email_id:
                                    # CRITICAL: Use full content from index, not just snippet
                                    full_content = result_item.get('content', '') or ''
                                    email_data = {
                                        'id': email_id,
                                        'threadId': metadata.get('thread_id', ''),
                                        'subject': metadata.get('subject', 'No Subject'),
                                        'sender': metadata.get('sender') or metadata.get('from', 'Unknown'),
                                        'from': metadata.get('sender') or metadata.get('from', 'Unknown'),
                                        'date': metadata.get('timestamp') or metadata.get('date') or metadata.get('created_at', ''),
                                        'snippet': full_content[:200],  # Keep snippet for backward compatibility
                                        'body': full_content,  # CRITICAL: Include full body content from index
                                        'labels': metadata.get('labels', []) if isinstance(metadata.get('labels'), list) else (metadata.get('labels', '').split(', ') if metadata.get('labels') else []),
                                        'has_attachments': metadata.get('has_attachments', False),
                                        'folder': metadata.get('folder', folder),
                                        '_source': 'hybrid_graphrag'
                                    }
                                    hybrid_results.append(email_data)
                        
                        logger.info(f"[EMAIL_SERVICE] HybridIndexCoordinator.query() returned {len(hybrid_results)} emails (two-step flow: Pinecone → Neo4j)")
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"[EMAIL_SERVICE] HybridIndexCoordinator query timed out. Falling back to direct queries.")
                        hybrid_results = []
                    except TimeoutError:
                        logger.warning(f"[EMAIL_SERVICE] HybridIndexCoordinator query timed out. Falling back to direct queries.")
                        hybrid_results = []
                    except AttributeError as e:
                        logger.warning(f"[EMAIL_SERVICE] HybridIndexCoordinator query failed - method not available: {e}. Falling back to direct queries.")
                        hybrid_results = []
                    except ConnectionError as e:
                        logger.warning(f"[EMAIL_SERVICE] HybridIndexCoordinator query failed - connection error: {e}. Falling back to direct queries.")
                        hybrid_results = []
                    except Exception as e:
                        logger.warning(f"[EMAIL_SERVICE] HybridIndexCoordinator query failed: {e}, trying direct queries", exc_info=True)
                        hybrid_results = []
                
                # Strategy B: Use direct Neo4j queries for pure structured queries (optimization)
                # This is more efficient when we have exact filters and no semantic query
                graph_results = []
                if has_structured_filters and not has_semantic_query and not hybrid_results:
                    try:
                        loop = None
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        if loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(
                                    lambda: asyncio.run(
                                        self._query_neo4j_for_emails(
                                            from_email=from_email,
                                            after_date=after_date,
                                            before_date=before_date,
                                            subject=subject,
                                            folder=folder,
                                            is_unread=is_unread,
                                            limit=limit
                                        )
                                    )
                                )
                                graph_results = future.result(timeout=5.0)
                        else:
                            graph_results = loop.run_until_complete(
                                self._query_neo4j_for_emails(
                                    from_email=from_email,
                                    after_date=after_date,
                                    before_date=before_date,
                                    subject=subject,
                                    folder=folder,
                                    is_unread=is_unread,
                                    limit=limit
                                )
                            )
                        logger.info(f"[EMAIL_SERVICE] Direct Neo4j query returned {len(graph_results)} emails")
                    except Exception as e:
                        logger.warning(f"[EMAIL_SERVICE] Direct Neo4j query failed: {e}")
                        graph_results = []
                
                # Combine results: prioritize hybrid results (architecture pattern), supplement with direct Neo4j
                combined_results = []
                seen_ids = set()
                
                # Add hybrid results first (follows architecture two-step flow)
                for email_data in hybrid_results:
                    email_id = email_data.get('id')
                    if email_id and email_id not in seen_ids:
                        seen_ids.add(email_id)
                        combined_results.append(email_data)
                
                # Add direct Neo4j results if we have space and no hybrid results
                if not hybrid_results:
                    for email_data in graph_results:
                        email_id = email_data.get('id')
                        if email_id and email_id not in seen_ids:
                            seen_ids.add(email_id)
                            email_data['_source'] = 'neo4j_direct'
                            combined_results.append(email_data)
                
                if len(combined_results) >= limit * 0.7:  # At least 70% of requested results
                    logger.info(f"[EMAIL_SERVICE] Hybrid search found {len(combined_results)} emails (hybrid: {len(hybrid_results)}, direct_neo4j: {len(graph_results)})")
                    return combined_results[:limit]
                elif len(combined_results) > 0:
                    logger.info(f"[EMAIL_SERVICE] Hybrid search found {len(combined_results)} emails, supplementing with Gmail API")
                    # Will fall through to Gmail API below
                else:
                    logger.info(f"[EMAIL_SERVICE] Hybrid search found 0 emails, falling back to Gmail API")
                    
            except Exception as e:
                logger.warning(f"[EMAIL_SERVICE] Hybrid search failed: {e}, falling back to vector-only search", exc_info=True)
        
        # Fallback: Try vector-only approach if RAG engine is available (no graph)
        # CRITICAL: Only use semantic search if we have a meaningful query or structured filters
        # Generic queries like "email" cause timeouts and poor results
        has_meaningful_query = query and len(query.strip()) > 3 and query.strip().lower() not in ['email', 'emails', 'mail']
        has_structured_filters = from_email or after_date or before_date or subject or is_unread is not None
        
        # CRITICAL: Validate rag_engine exists and is callable before using it
        rag_engine_available = (
            self.rag_engine is not None and 
            hasattr(self.rag_engine, 'search') and 
            callable(getattr(self.rag_engine, 'search', None))
        )
        
        if rag_engine_available and (has_meaningful_query or (has_structured_filters and from_email)):
            try:
                logger.info(f"[EMAIL_SERVICE] Attempting vector-only search: query='{query}', from_email='{from_email}', after_date='{after_date}', before_date='{before_date}'")
                
                # Build search query for index
                # Use query text or build from filters for better semantic matching
                search_query = None
                if has_meaningful_query:
                    search_query = query.strip()
                elif from_email:
                    # Only use semantic search if we have a sender filter (helps narrow results)
                    search_query = f"email from {from_email}"
                elif subject:
                    search_query = f"email subject {subject}"
                
                # Skip semantic search if we don't have a meaningful query
                # Generic queries cause timeouts and poor results
                if not search_query:
                    logger.info(f"[EMAIL_SERVICE] Skipping semantic search - no meaningful query and no sender filter. Will use Gmail API directly.")
                    index_results = []
                else:
                # Search index - get more results to account for post-filtering
                    # CRITICAL: rag_engine.search is synchronous, so call it directly
                    # Use thread pool if we're in an async context to avoid blocking
                    index_results = []
                    try:
                        # Validate search_query is not empty and is a string
                        if not search_query or not isinstance(search_query, str) or len(search_query.strip()) == 0:
                            logger.warning(f"[EMAIL_SERVICE] Invalid search query: '{search_query}', skipping index search")
                            index_results = []
                        else:
                            # Check if we're in an async event loop
                            loop = None
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = None
                            
                            # Use shorter timeout for generic queries to avoid hanging
                            timeout_seconds = 5.0 if search_query.lower() in ['email', 'emails'] else 10.0
                            
                            if loop and loop.is_running():
                                # We're in an async context - use thread pool to avoid blocking
                                import concurrent.futures
                                with concurrent.futures.ThreadPoolExecutor() as executor:
                                    future = executor.submit(
                        self.rag_engine.search,
                        query=search_query,
                                        k=limit * 5
                                    )
                                    index_results = future.result(timeout=timeout_seconds)
                            else:
                                # No event loop or not running - call directly
                                index_results = self.rag_engine.search(
                                    query=search_query,
                                    k=limit * 5  # Get 5x results to account for filtering
                                )
                            
                            # Validate results - ensure it's a list
                            if not isinstance(index_results, list):
                                logger.warning(f"[EMAIL_SERVICE] Index search returned non-list result: {type(index_results)}, converting to empty list")
                                index_results = []
                                
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"[EMAIL_SERVICE] Index search timed out for query '{search_query}'. Skipping semantic search and using Gmail API.")
                        index_results = []
                    except TimeoutError:
                        logger.warning(f"[EMAIL_SERVICE] Index search timed out for query '{search_query}'. Skipping semantic search and using Gmail API.")
                        index_results = []
                    except AttributeError as e:
                        logger.warning(f"[EMAIL_SERVICE] Index search failed - rag_engine.search method not available: {e}. Falling back to Gmail API.")
                        index_results = []
                    except ConnectionError as e:
                        logger.warning(f"[EMAIL_SERVICE] Index search failed - connection error: {e}. Falling back to Gmail API.")
                        index_results = []
                    except Exception as e:
                        logger.warning(f"[EMAIL_SERVICE] Index search failed: {e}. Falling back to Gmail API.", exc_info=True)
                        index_results = []
                
                # Validate index_results before processing
                if not isinstance(index_results, list):
                    logger.warning(f"[EMAIL_SERVICE] Index search returned non-list result: {type(index_results)}, treating as empty")
                    index_results = []
                
                logger.info(f"[EMAIL_SERVICE] Index search returned {len(index_results)} results, applying filters (from_email='{from_email}', after_date='{after_date}', before_date='{before_date}')")
                
                # Log sample of first few results to diagnose filtering issues
                if index_results and len(index_results) > 0:
                    logger.info(f"[EMAIL_SERVICE] Sample index results (first 3):")
                    for i, result in enumerate(index_results[:3]):
                        if not isinstance(result, dict):
                            logger.warning(f"[EMAIL_SERVICE] Index result {i+1} is not a dict: {type(result)}")
                            continue
                        metadata = result.get('metadata', {})
                        if not isinstance(metadata, dict):
                            metadata = {}
                        logger.info(f"  [{i+1}] sender='{metadata.get('sender', 'N/A')}', from='{metadata.get('from', 'N/A')}', date='{metadata.get('date', 'N/A')}', subject='{metadata.get('subject', 'N/A')[:60]}'")
                
                # Convert RAG results to EmailService format and apply filters
                emails_from_index = []
                seen_ids = set()
                filtered_count = {'sender': 0, 'date': 0, 'duplicate': 0, 'other': 0}
                
                for result in index_results:
                    # Validate result structure
                    if not isinstance(result, dict):
                        filtered_count['other'] += 1
                        continue
                    
                    metadata = result.get('metadata', {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    # Try multiple field names for email ID
                    email_id = metadata.get('email_id') or metadata.get('message_id') or metadata.get('id') or result.get('id')
                    
                    # Skip duplicates (same email_id)
                    if email_id and email_id in seen_ids:
                        filtered_count['duplicate'] += 1
                        continue
                    if email_id:
                        seen_ids.add(email_id)
                    
                    # Debug: Log metadata for first few results to diagnose filtering issues
                    if len(emails_from_index) < 5:
                        logger.info(f"[EMAIL_SERVICE] Index result sample {len(emails_from_index)+1}: sender='{metadata.get('sender')}', date='{metadata.get('date')}', subject='{metadata.get('subject', '')[:50]}'")
                    
                    # Apply filters BEFORE creating email_data (more efficient)
                    # Filter by sender - use intelligent matching
                    if from_email:
                        sender_meta_raw = metadata.get('sender', '') or metadata.get('from', '') or ''
                        sender_meta = sender_meta_raw.lower().strip()
                        from_email_lower = from_email.lower().strip()
                        
                        # Try multiple matching strategies (in order of specificity)
                        sender_matches = False
                        match_reason = None
                        
                        # Strategy 1: Exact match
                        if from_email_lower == sender_meta:
                            sender_matches = True
                            match_reason = "exact"
                        
                        # Strategy 2: Substring match (name in email or email in name)
                        # This is the most common case: "alvaro" should match "alvaro santana-acuna" or "alvaro.santana-acuna@domain.com"
                        if not sender_matches:
                            # Check if query is substring of sender (handles "alvaro" in "alvaro.santana-acuna@domain.com")
                            if from_email_lower in sender_meta:
                                sender_matches = True
                                match_reason = f"substring (query '{from_email_lower}' in sender '{sender_meta_raw}')"
                            # Check if sender is substring of query (handles full name in query)
                            elif sender_meta in from_email_lower:
                                sender_matches = True
                                match_reason = f"substring (sender '{sender_meta_raw}' in query '{from_email_lower}')"
                        
                        # Strategy 3: Extract name from email format "Name <email@domain.com>"
                        # Check this BEFORE email local part matching for better accuracy
                        if not sender_matches and '<' in sender_meta_raw:
                            name_part = sender_meta_raw.split('<')[0].strip().lower()
                            if name_part and (from_email_lower in name_part or name_part in from_email_lower):
                                sender_matches = True
                                match_reason = f"name_from_format ({name_part})"
                        
                        # Strategy 4: Extract email local part and match with name parts
                        # e.g., "Alvaro Santana-Acuna" should match "santana@whitman.edu"
                        if not sender_matches and '@' in sender_meta:
                            email_local_part = sender_meta.split('@')[0].lower()
                            # Split query name into parts (handle hyphens and spaces)
                            query_name_parts = [p for p in from_email_lower.replace('-', ' ').replace('_', ' ').replace('.', ' ').split() if len(p) > 2]
                            # Check if any name part matches the email local part (or vice versa)
                            for name_part in query_name_parts:
                                if name_part in email_local_part or email_local_part in name_part:
                                    sender_matches = True
                                    match_reason = f"email_local_part ({name_part} in {email_local_part})"
                                    break
                        
                        # Strategy 5: Check if sender contains any significant name parts from query
                        # This handles cases where sender is "Alvaro Santana-Acuna" and query is "Alvaro"
                        # Also handles email addresses like "alvaro.santana-acuna@domain.com" matching "alvaro"
                        if not sender_matches:
                            # Split query into parts (handle various separators)
                            query_name_parts = [p for p in from_email_lower.replace('-', ' ').replace('_', ' ').replace('.', ' ').split() if len(p) > 2]
                            for name_part in query_name_parts:
                                # Check if name part appears anywhere in sender (including email addresses)
                                if name_part in sender_meta:
                                    sender_matches = True
                                    match_reason = f"name_part_match ({name_part} in sender)"
                                    break
                        
                        # Strategy 6: Word boundary matching - check if query words appear as whole words in sender
                        if not sender_matches:
                            query_words = [w for w in from_email_lower.replace('-', ' ').replace('_', ' ').replace('.', ' ').split() if len(w) > 3]
                            sender_words = sender_meta.replace('-', ' ').replace('_', ' ').replace('.', ' ').split()
                            for query_word in query_words:
                                if query_word in sender_words:
                                    sender_matches = True
                                    match_reason = f"word_match ({query_word})"
                                    break
                        
                        # Strategy 7: For email addresses, check if query name appears before @ symbol
                        # e.g., "alvaro" should match "alvaro.santana-acuna@whitman.edu"
                        if not sender_matches and '@' in sender_meta:
                            email_local_part = sender_meta.split('@')[0]
                            # Check if entire query (or any part) matches the local part
                            if from_email_lower in email_local_part:
                                sender_matches = True
                                match_reason = f"email_local_part_query_match ({from_email_lower} in {email_local_part})"
                            # Also check individual words from query
                            elif not sender_matches:
                                query_words = from_email_lower.replace('-', ' ').replace('_', ' ').replace('.', ' ').split()
                                for query_word in query_words:
                                    if len(query_word) > 2 and query_word in email_local_part:
                                        sender_matches = True
                                        match_reason = f"email_local_part_word_match ({query_word} in {email_local_part})"
                                    break
                        
                        if not sender_matches:
                            filtered_count['sender'] += 1
                            # Always log first 10 failures for debugging sender matching issues
                            if filtered_count['sender'] <= 10:
                                logger.warning(f"[EMAIL_SERVICE] ❌ Sender filter failed: query='{from_email_lower}' not found in sender='{sender_meta_raw}' (email_id: {email_id}, subject: '{metadata.get('subject', 'N/A')[:50]}')")
                            continue
                        else:
                            # Always log successful matches for first 5 to verify matching works
                            if len(emails_from_index) < 5:
                                logger.info(f"[EMAIL_SERVICE] ✓ Sender match SUCCESS: query='{from_email_lower}' matches sender='{sender_meta_raw}' via {match_reason} (email_id: {email_id})")
                    
                    # Filter by subject - CRITICAL: Use intelligent matching
                    if subject:
                        subject_meta = metadata.get('subject', '').strip()
                        subject_lower = subject.lower().strip()
                        subject_meta_lower = subject_meta.lower()
                        
                        # Skip "No Subject" emails when subject is explicitly provided
                        if not subject_meta or subject_meta_lower in ['no subject', '(no subject)', '']:
                            filtered_count['other'] += 1
                            if filtered_count['other'] <= 3:
                                logger.debug(f"[EMAIL_SERVICE] Filtered out 'No Subject' email when subject '{subject}' was requested")
                            continue
                        
                        # Try multiple matching strategies
                        subject_matches = False
                        
                        # Strategy 1: Exact match (case-insensitive)
                        if subject_lower == subject_meta_lower:
                            subject_matches = True
                            logger.debug(f"[EMAIL_SERVICE] Exact subject match: '{subject}' == '{subject_meta}'")
                        
                        # Strategy 2: Query subject contained in email subject
                        elif subject_lower in subject_meta_lower:
                            subject_matches = True
                            logger.debug(f"[EMAIL_SERVICE] Subject substring match: '{subject}' in '{subject_meta}'")
                        
                        # Strategy 3: Email subject contained in query subject (handles partial matches)
                        elif subject_meta_lower in subject_lower:
                            subject_matches = True
                            logger.debug(f"[EMAIL_SERVICE] Subject reverse substring match: '{subject_meta}' in '{subject}'")
                        
                        # Strategy 4: Word-by-word matching (at least 50% of words match)
                        else:
                            query_words = set([w for w in subject_lower.split() if len(w) >= 3])
                            meta_words = set([w for w in subject_meta_lower.split() if len(w) >= 3])
                            if query_words and meta_words:
                                matching_words = query_words.intersection(meta_words)
                                match_ratio = len(matching_words) / max(len(query_words), len(meta_words))
                                if match_ratio >= 0.5:  # At least 50% word overlap
                                    subject_matches = True
                                    logger.debug(f"[EMAIL_SERVICE] Subject word match: {len(matching_words)}/{max(len(query_words), len(meta_words))} words match")
                        
                        if not subject_matches:
                            filtered_count['other'] += 1
                            if filtered_count['other'] <= 3:
                                logger.debug(f"[EMAIL_SERVICE] Subject filter failed: query='{subject}' not matching subject='{subject_meta}'")
                            continue
                    
                    # Filter by folder
                    if folder and folder != 'inbox':  # 'inbox' is default
                        folder_meta = metadata.get('folder', 'inbox').lower()
                        if folder.lower() != folder_meta:
                            continue
                    
                    # Filter by unread status
                    if is_unread is not None:
                        is_unread_meta = metadata.get('is_unread', False)
                        if is_unread != is_unread_meta:
                            continue
                    
                    # Filter by date range
                    if after_date or before_date:
                        # Try multiple date field names
                        email_date_str = metadata.get('timestamp') or metadata.get('date') or metadata.get('created_at') or ''
                        if email_date_str:
                            try:
                                from datetime import datetime
                                import pytz
                                
                                # Parse date string (could be YYYY-MM-DD or ISO format)
                                if isinstance(email_date_str, datetime):
                                    email_date = email_date_str
                                    if email_date.tzinfo is None:
                                        email_date = pytz.UTC.localize(email_date)
                                elif 'T' in str(email_date_str):
                                    # ISO format: 2025-11-20T10:05:00Z or 2025-11-20T10:05:00+00:00
                                    email_date_str_clean = str(email_date_str).replace('Z', '+00:00')
                                    email_date = datetime.fromisoformat(email_date_str_clean)
                                    if email_date.tzinfo is None:
                                        email_date = pytz.UTC.localize(email_date)
                                else:
                                    # YYYY-MM-DD format - assume UTC midnight
                                    email_date = datetime.strptime(str(email_date_str), '%Y-%m-%d')
                                    email_date = pytz.UTC.localize(email_date)
                                
                                # Parse filter dates (Gmail format: YYYY/MM/DD, represents UTC dates)
                                # STRICT date filtering: emails must be within the exact date range
                                date_filter_passed = True
                                
                                if after_date:
                                    after_dt = datetime.strptime(after_date, '%Y/%m/%d')
                                    after_dt = pytz.UTC.localize(after_dt)
                                    # STRICT: Email date must be >= after_date (inclusive start)
                                    if email_date.date() < after_dt.date():
                                        filtered_count['date'] += 1
                                        if filtered_count['date'] <= 3:  # Log first 3 failures
                                            logger.debug(f"[EMAIL_SERVICE] STRICT FILTER: Filtered out {email_id}: date {email_date.date()} < after_date {after_dt.date()}")
                                        date_filter_passed = False
                                
                                if before_date and date_filter_passed:
                                    before_dt = datetime.strptime(before_date, '%Y/%m/%d')
                                    before_dt = pytz.UTC.localize(before_dt)
                                    # STRICT: Email date must be < before_date (exclusive end, as Gmail API uses)
                                    if email_date.date() >= before_dt.date():
                                        filtered_count['date'] += 1
                                        if filtered_count['date'] <= 3:  # Log first 3 failures
                                            logger.debug(f"[EMAIL_SERVICE] STRICT FILTER: Filtered out {email_id}: date {email_date.date()} >= before_date {before_dt.date()}")
                                        date_filter_passed = False
                                
                                if not date_filter_passed:
                                    continue  # Skip this email - doesn't match date filter
                                
                                logger.debug(f"[EMAIL_SERVICE] Date filter PASSED for {email_id}: {email_date.date()} (after: {after_date}, before: {before_date})")
                            except Exception as e:
                                logger.warning(f"[EMAIL_SERVICE] Date filtering failed for {email_id}: {e}, email_date_str: {email_date_str}")
                                # If date parsing fails, include the email (don't filter out)
                        else:
                            logger.debug(f"[EMAIL_SERVICE] No date metadata for {email_id}, including in results")
                    
                    # Filter by recipient
                    if to_email:
                        to_meta = str(metadata.get('to', '')).lower()
                        if to_email.lower() not in to_meta:
                            continue
                    
                    # Filter by attachment
                    if has_attachment:
                        if not metadata.get('has_attachments', False):
                            continue
                    
                    # Extract email data from metadata (handle multiple field name variations)
                    # CRITICAL: Use full content from index, not just snippet
                    full_content = result.get('content', '') or ''
                    email_data = {
                        'id': email_id or result.get('id', ''),
                        'threadId': metadata.get('thread_id') or metadata.get('threadId', ''),
                        'subject': metadata.get('subject', 'No Subject'),
                        'sender': metadata.get('sender') or metadata.get('from', 'Unknown'),
                        'from': metadata.get('sender') or metadata.get('from', 'Unknown'),
                        'date': metadata.get('timestamp') or metadata.get('date') or metadata.get('created_at', ''),
                        'snippet': full_content[:200] if full_content else '',  # Keep snippet for backward compatibility
                        'body': full_content,  # CRITICAL: Include full body content from index
                        'labels': metadata.get('labels', []) if isinstance(metadata.get('labels'), list) else (metadata.get('labels', '').split(', ') if metadata.get('labels') else []),
                        'has_attachments': metadata.get('has_attachments', False),
                        'folder': metadata.get('folder', folder),
                        '_source': 'index'  # Mark as from index for debugging
                    }
                    
                    emails_from_index.append(email_data)
                    
                    # Stop if we have enough results
                    if len(emails_from_index) >= limit:
                        break
                
                # Log filtering statistics
                logger.info(f"[EMAIL_SERVICE] Index filtering stats: {len(emails_from_index)} passed, {filtered_count['sender']} filtered by sender, {filtered_count['date']} filtered by date, {filtered_count['duplicate']} duplicates, {filtered_count['other']} other")
                
                # If we got good results from index, return them
                if len(emails_from_index) >= limit * 0.7:  # At least 70% of requested results
                    logger.info(f"[EMAIL_SERVICE] Found {len(emails_from_index)} emails from index (fast path)")
                    return emails_from_index[:limit]
                elif len(emails_from_index) > 0:
                    logger.info(f"[EMAIL_SERVICE] Found {len(emails_from_index)} emails from index, supplementing with Gmail API")
                    # We'll supplement with Gmail API results below
                else:
                    logger.warning(f"[EMAIL_SERVICE] No results from index after filtering (total index results: {len(index_results)}, filtered: sender={filtered_count['sender']}, date={filtered_count['date']}, duplicate={filtered_count['duplicate']}), falling back to Gmail API")
                    
            except Exception as e:
                logger.warning(f"[EMAIL_SERVICE] Index search failed, falling back to Gmail API: {e}")
                # Fall through to Gmail API search
        
        # Fallback to Gmail API (original implementation)
        self._ensure_available()
        
        try:
            logger.info(f"[EMAIL_SERVICE] Searching emails via Gmail API: query='{query}', folder='{folder}', from_email='{from_email}', after_date='{after_date}', before_date='{before_date}'")
            
            # Build Gmail search query - don't use raw query string, build proper Gmail query
            search_parts = []
            
            # Add folder/label filter
            if folder and folder != "inbox":
                search_parts.append(f"in:{folder}")
            else:
                search_parts.append("in:inbox")
            
            # Add sender filter (most important)
            if from_email:
                # Try multiple sender query formats for better matching
                # Gmail supports: from:name, from:email, from:"Full Name"
                search_parts.append(f'from:"{from_email}"')
                # Also try without quotes for email addresses
                if '@' not in from_email:
                    # If it's a name, also try partial matches
                    name_parts = from_email.split()
                    if len(name_parts) > 1:
                        # Try last name (often in email)
                        search_parts.append(f'from:{name_parts[-1]}')
            
            # Add date/time filters
            # Use newer_than for time-based queries (more accurate for recent emails)
            if newer_than_value:
                search_parts.append(f"newer_than:{newer_than_value}")
                logger.info(f"[EMAIL_SERVICE] Using time-based filter: newer_than:{newer_than_value}")
            else:
                # Use date filters for date-based queries
                if after_date:
                    search_parts.append(f"after:{after_date}")
                if before_date:
                    search_parts.append(f"before:{before_date}")
            
            # Add other filters
            if to_email:
                search_parts.append(f"to:{to_email}")
            if subject:
                search_parts.append(f'subject:"{subject}"')
            if has_attachment:
                search_parts.append("has:attachment")
            if is_unread is not None:
                search_parts.append("is:unread" if is_unread else "is:read")
            
            # Don't add raw query string - it's not a valid Gmail query format
            # Only use structured filters above
            
            gmail_query = " ".join(search_parts) if search_parts else "in:inbox"
            
            results = self.gmail_client.search_emails(
                query=gmail_query,
                folder=folder,
                limit=limit
            )
            
            logger.info(f"[EMAIL_SERVICE] Found {len(results)} emails from Gmail API")
            return results
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Email search failed: {e}")
            raise EmailSearchException(
                f"Email search failed: {str(e)}",
                service_name="email",
                details={'query': query, 'folder': folder}
            )
    
    def list_unread_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get unread emails - OPTIMIZED: Uses index first
        
        This method now queries the index first for faster retrieval.
        """
        return self.search_emails(is_unread=True, limit=limit)
    
    def list_recent_emails(self, limit: int = 10, folder: str = "inbox") -> List[Dict[str, Any]]:
        """
        Get recent emails from folder - OPTIMIZED: Uses index first
        
        This method now queries the index first for faster retrieval.
        """
        return self.search_emails(folder=folder, limit=limit)
    
    # ===================================================================
    # BULK OPERATIONS
    # ===================================================================
    
    def mark_as_read(self, message_ids: List[str]) -> Dict[str, Any]:
        """Mark multiple emails as read"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.mark_as_read(msg_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to mark {msg_id} as read: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count
            }
        except Exception as e:
            raise EmailServiceException(
                f"Bulk mark as read failed: {str(e)}",
                service_name="email"
            )
    
    def mark_as_unread(self, message_ids: List[str]) -> Dict[str, Any]:
        """Mark multiple emails as unread"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.mark_as_unread(msg_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to mark {msg_id} as unread: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count
            }
        except Exception as e:
            raise EmailServiceException(
                f"Bulk mark as unread failed: {str(e)}",
                service_name="email"
            )
    
    def archive_emails(self, message_ids: List[str]) -> Dict[str, Any]:
        """Archive multiple emails"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.archive_email(msg_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to archive {msg_id}: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count
            }
        except Exception as e:
            raise EmailServiceException(
                f"Bulk archive failed: {str(e)}",
                service_name="email"
            )
    
    def delete_emails(self, message_ids: List[str]) -> Dict[str, Any]:
        """Delete multiple emails"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.delete_email(msg_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {msg_id}: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count
            }
        except Exception as e:
            raise EmailServiceException(
                f"Bulk delete failed: {str(e)}",
                service_name="email"
            )
    
    # ===================================================================
    # ORGANIZATION
    # ===================================================================
    
    def apply_label(self, message_ids: List[str], label: str) -> Dict[str, Any]:
        """Apply a label to multiple emails"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.add_label(msg_id, label)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to label {msg_id}: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count,
                'label': label
            }
        except Exception as e:
            raise EmailServiceException(
                f"Failed to apply label: {str(e)}",
                service_name="email"
            )
    
    def remove_label(self, message_ids: List[str], label: str) -> Dict[str, Any]:
        """Remove a label from multiple emails"""
        self._ensure_available()
        
        try:
            success_count = 0
            for msg_id in message_ids:
                try:
                    self.gmail_client.remove_label(msg_id, label)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to remove label from {msg_id}: {e}")
            
            return {
                'total': len(message_ids),
                'success': success_count,
                'failed': len(message_ids) - success_count,
                'label': label
            }
        except Exception as e:
            raise EmailServiceException(
                f"Failed to remove label: {str(e)}",
                service_name="email"
            )
    
    # ===================================================================
    # ANALYTICS
    # ===================================================================
    
    def get_inbox_stats(self) -> Dict[str, Any]:
        """Get inbox statistics"""
        self._ensure_available()
        
        try:
            # Get counts for different categories
            total_count = len(self.search_emails(folder="inbox", limit=1000))
            unread_count = len(self.list_unread_emails(limit=1000))
            
            return {
                'total_emails': total_count,
                'unread_emails': unread_count,
                'read_emails': total_count - unread_count,
                'unread_percentage': (unread_count / total_count * 100) if total_count > 0 else 0
            }
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to get inbox stats: {e}")
            raise EmailServiceException(
                f"Failed to get inbox stats: {str(e)}",
                service_name="email"
            )
    
    # ===================================================================
    # RAG INTEGRATION
    # ===================================================================
    
    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using RAG
        
        Args:
            query: Natural language query
            limit: Maximum results
            filters: Additional filters (date range, sender, etc.)
            
        Returns:
            List of relevant emails ranked by semantic similarity
        """
        if not self.rag_engine:
            logger.warning("[EMAIL_SERVICE] RAG engine not available, falling back to regular search")
            return self.search_emails(query=query, limit=limit)
        
        try:
            logger.info(f"[EMAIL_SERVICE] Performing semantic search: '{query}'")
            
            results = self.rag_engine.search(
                query=query,
                limit=limit,
                filters=filters
            )
            
            return results
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Semantic search failed: {e}")
            # Fallback to regular search
            return self.search_emails(query=query, limit=limit)
    
    # ===================================================================
    # INTEGRATIONS
    # ===================================================================
    
    def create_event_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: str,
        calendar_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Create a calendar event from an email
        
        Uses NLP to extract meeting details from email content and creates
        a calendar event with smart scheduling suggestions.
        
        Args:
            email_id: Email ID for linking
            email_subject: Email subject
            email_body: Email body content
            calendar_service: Optional calendar service instance
            
        Returns:
            Created event details
            
        Raises:
            EmailIntegrationException: If event creation fails
        """
        try:
            logger.info(f"[EMAIL_SERVICE] Creating event from email: {email_id}")
            
            if not calendar_service:
                from .calendar_service import CalendarService
                calendar_service = CalendarService(
                    config=self.config,
                    credentials=self.credentials
                )
            
            # Extract meeting details using intelligent LLM-based extraction
            # Leverages the rich architecture with FlexibleDateParser and LLM capabilities
            from datetime import datetime, timedelta
            from langchain_core.messages import HumanMessage
            import json
            
            # Initialize intelligent parsers
            date_parser = None
            llm_client = None
            
            try:
                from ..utils import FlexibleDateParser
                date_parser = FlexibleDateParser(self.config)
            except Exception as e:
                logger.debug(f"FlexibleDateParser not available: {e}")
            
            try:
                from ..ai.llm_factory import LLMFactory
                llm_client = LLMFactory.get_llm_for_provider(self.config, temperature=0.1)
            except Exception as e:
                logger.debug(f"LLM client not available: {e}")
            
            # Use LLM to extract meeting details intelligently
            event_title = email_subject
            start_time = None
            end_time = None
            location = None
            attendees = []
            
            if llm_client:
                try:
                    # Build comprehensive extraction prompt
                    extraction_prompt = f"""Extract meeting/event details from this email. Be precise and extract only what's explicitly mentioned.

Subject: {email_subject}
Body: {email_body[:2000]}

Extract the following in JSON format:
{{
    "event_title": "Meeting/event title (use subject if no specific title, but clean it up)",
    "date_time": "Complete date and time expression (e.g., 'tomorrow at 2pm', 'next Monday at 10am', 'November 20th at 3:30pm', 'today at 4pm')",
    "location": "Meeting location/venue (if mentioned)",
    "attendees": ["list of attendee names or emails if mentioned"],
    "duration_hours": 1.0,
    "confidence": 0.0-1.0
}}

CRITICAL RULES:
- event_title: Use the email subject, but remove prefixes like "Re:", "Fwd:", etc. Only add "Meeting:" if it's clearly a meeting invitation
- date_time: Extract the COMPLETE date+time expression as written (e.g., "tomorrow at 2pm", not just "2pm")
- If no specific time is mentioned, return null for date_time
- If only time is mentioned (e.g., "at 2pm"), assume it's for today unless context suggests otherwise
- duration_hours: Default to 1.0 if not specified
- confidence: Rate how confident you are in the extraction (0.0-1.0)

Respond ONLY with valid JSON, no other text."""

                    response = llm_client.invoke([HumanMessage(content=extraction_prompt)])
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    # Ensure response_text is a string for regex matching
                    if not isinstance(response_text, str):
                        response_text = str(response_text) if response_text else ""
                    
                    if response_text:
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            extracted = json.loads(json_match.group(0))
                            
                            # Extract event title
                            if extracted.get('event_title'):
                                event_title = extracted['event_title'].strip()
                            
                            # Extract date/time using FlexibleDateParser
                            date_time_expr = extracted.get('date_time')
                            if date_time_expr and date_parser:
                                try:
                                    date_range = date_parser.parse_date_expression(date_time_expr, prefer_future=True)
                                    if date_range:
                                        start_time = date_range['start']
                                        # Use duration if specified, otherwise default to 1 hour
                                        duration_hours = extracted.get('duration_hours', 1.0)
                                        end_time = start_time + timedelta(hours=duration_hours)
                                        logger.info(f"[EMAIL_SERVICE] Extracted date/time: {date_time_expr} → {start_time} to {end_time}")
                                except Exception as e:
                                    logger.warning(f"[EMAIL_SERVICE] Date parsing failed: {e}")
                            
                            # Extract location and attendees
                            if extracted.get('location'):
                                location = extracted['location'].strip()
                            if extracted.get('attendees'):
                                attendees = extracted['attendees'] if isinstance(extracted['attendees'], list) else []
                            
                            logger.info(f"[EMAIL_SERVICE] LLM extracted meeting details: title='{event_title}', confidence={extracted.get('confidence', 0.0)}")
                            
                except Exception as e:
                    logger.warning(f"[EMAIL_SERVICE] LLM extraction failed, using fallback: {e}")
            
            # Fallback: Use FlexibleDateParser directly if LLM didn't extract time
            if not start_time and date_parser:
                try:
                    # Try to extract date/time from email body directly
                    combined_text = f"{email_subject} {email_body[:500]}"
                    date_range = date_parser.parse_date_expression(combined_text, prefer_future=True)
                    if date_range:
                        start_time = date_range['start']
                        end_time = date_range.get('end', start_time + timedelta(hours=1))
                        logger.info(f"[EMAIL_SERVICE] Fallback: Extracted date/time using FlexibleDateParser: {start_time} to {end_time}")
                except Exception as e:
                    logger.debug(f"[EMAIL_SERVICE] FlexibleDateParser fallback failed: {e}")
            
            # Final fallback: Default to 1 hour from now if no time found
            if not start_time:
                start_time = datetime.now() + timedelta(hours=1)
                end_time = start_time + timedelta(hours=1)
                logger.info(f"[EMAIL_SERVICE] Using default time: 1 hour from now")
            
            # Create calendar event with extracted details
            event_data = {
                'summary': event_title,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'description': f"Created from email: {email_id}\n\n{email_body[:500]}..."
            }
            
            # Add location and attendees if extracted
            if location:
                event_data['location'] = location
            if attendees:
                event_data['attendees'] = attendees
            
            event = calendar_service.create_event(**event_data)
            
            logger.info(f"[EMAIL_SERVICE] Event created from email: {event.get('id', 'unknown')}")
            return event
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to create event from email: {e}")
            from .exceptions import EmailIntegrationException
            raise EmailIntegrationException(
                f"Failed to create event from email: {str(e)}",
                service_name="email",
                details={'email_id': email_id}
            )
    
    def create_task_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: Optional[str] = None,
        auto_extract: bool = False,
        task_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Create a task from an email
        
        Args:
            email_id: Email ID for linking
            email_subject: Email subject
            email_body: Email body (optional)
            auto_extract: Use AI to extract action items
            task_service: Optional task service instance
            
        Returns:
            Created task details
        """
        try:
            logger.info(f"[EMAIL_SERVICE] Creating task from email: {email_id}")
            
            if not task_service:
                from .task_service import TaskService
                task_service = TaskService(
                    config=self.config,
                    credentials=self.credentials
                )
            
            # Use the task service's email integration method
            return task_service.create_task_from_email(
                email_id=email_id,
                email_subject=email_subject,
                email_body=email_body,
                auto_extract=auto_extract
            )
            
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Failed to create task from email: {e}")
            from .exceptions import EmailIntegrationException
            raise EmailIntegrationException(
                f"Failed to create task from email: {str(e)}",
                service_name="email",
                details={'email_id': email_id}
            )
