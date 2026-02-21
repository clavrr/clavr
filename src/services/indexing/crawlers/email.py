"""
Email Crawler

Specific implementation of BaseIndexer for Gmail.
Refactored from legacy 'IntelligentEmailIndexer' to fit the Unified Indexing Architecture.

Responsibilities:
- Fetch new emails from Gmail (incremental sync).
- Parse emails, attachments (receipts/docs), and sub-entities (tasks/contacts).
- Return ParsedNodes for the UnifiedIndexer to ingest.
"""
import os
import json
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set, Tuple
from google.auth.exceptions import RefreshError

from src.core.base.exceptions import AuthenticationExpiredError
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.parsers import EmailParser, ReceiptParser, AttachmentParser
from src.core.email.google_client import GoogleGmailClient
from src.ai.rag.processing.document_processor import DocumentProcessor
from src.ai.llm_factory import LLMFactory
from src.database import get_db_context
from src.database.models import User, ActionableItem
from sqlalchemy import select
from src.services.extraction.actionable_item_extractor import ActionableItemExtractor

logger = setup_logger(__name__)

class EmailCrawler(BaseIndexer):
    """
    Crawler that fetches and parses Gmail messages.
    """
    
    def __init__(
        self, 
        config: Config, 
        user_id: int, 
        rag_engine=None, 
        graph_manager=None,
        google_client: Optional[GoogleGmailClient] = None,
        topic_extractor=None,  # TopicExtractor for auto topic extraction
        temporal_indexer=None, # TemporalIndexer for time-based queries
        relationship_manager=None,
        entity_resolver=None,
        observer_service=None
    ):
        super().__init__(
            config=config, 
            user_id=user_id, 
            rag_engine=rag_engine, 
            graph_manager=graph_manager, 
            topic_extractor=topic_extractor, 
            temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager,
            entity_resolver=entity_resolver,
            observer_service=observer_service
        )
        self.google_client = google_client
        
        # Initialize LLM Client for intelligent parsing
        try:
            self.llm_client = LLMFactory.get_llm_for_provider(config)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM client for EmailCrawler: {e}")
            self.llm_client = None

        # Initialize parsers
        self.email_parser = EmailParser(llm_client=self.llm_client)
        self.receipt_parser = ReceiptParser(llm_client=self.llm_client)
        self.attachment_parser = AttachmentParser()
        
        # Initialize DocumentProcessor (if RAG engine available)
        self.document_processor = None
        if rag_engine:
            self.document_processor = DocumentProcessor(rag_engine=rag_engine)
            
        # Initialize Actionable Item Extractor
        self.actionable_extractor = ActionableItemExtractor(config)
            
        # Constants from ServiceConstants
        from src.services.service_constants import ServiceConstants
        self.INITIAL_INDEXING_DAYS = ServiceConstants.INITIAL_INDEXING_DAYS
        self.BATCH_SIZE = 50
        
        # Fetch user's email for SENT/RECEIVED linking
        self.user_email = None
        try:
            with get_db_context() as db:
                user = db.execute(select(User).where(User.id == user_id)).scalars().first()
                if user:
                    self.user_email = user.email
                    logger.debug(f"[{self.name}] Initialized with user email: {self.user_email}")
        except Exception as e:
            logger.warning(f"[{self.name}] Could not fetch user email: {e}")
        
    @property
    def name(self) -> str:
        return "email"

    async def fetch_delta(self) -> List[Dict[str, Any]]:
        """
        Fetch new emails since last sync.
        Uses 'Smart Indexing' logic:
        1. Check User metadata for last_indexed_timestamp.
        2. Query Gmail for messages after that time.
        3. Filter out already indexed messages.
        4. Fetch full content for new messages.
        """
        if not self.google_client or not self.google_client.is_available():
            logger.warning("[EmailCrawler] Google client unavailable, skipping sync")
            return []
            
        with get_db_context() as db_session:
            # 1. Get User State
            result = db_session.execute(select(User).where(User.id == self.user_id))
            user = result.scalars().first()
            
            if not user:
                logger.error(f"[EmailCrawler] User {self.user_id} not found")
                return []
                
            # Determine query
            if not user.last_indexed_timestamp:
                # Initial Sync
                days = self.INITIAL_INDEXING_DAYS
                start_date = datetime.now() - timedelta(days=days)
                date_str = start_date.strftime('%Y/%m/%d')
                logger.info(f"[EmailCrawler] Initial sync: fetching last {days} days (from {date_str})")
                query = f"after:{date_str}"
            else:
                # Incremental Sync
                last_indexed = user.last_indexed_timestamp
                # Configure query for emails since last index
                date_str = last_indexed.strftime('%Y/%m/%d')
                query = f"after:{date_str}"
                logger.info(f"[EmailCrawler] Incremental sync: fetching after {date_str}")

            try:
                # 2. List message IDs
                results = self.google_client.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=self.BATCH_SIZE
                ).execute()
                
                messages = results.get('messages', [])
                if not messages:
                    return []
                    
                # 3. Batch Check Existing (Deduplication)
                # Convert to our Doc ID format to check existence
                message_ids = [msg['id'] for msg in messages]
                already_indexed = await self._batch_check_indexed(message_ids)
                
                unindexed_ids = [mid for mid in message_ids if mid not in already_indexed]
                
                if not unindexed_ids:
                    logger.debug("[EmailCrawler] All fetched emails are already indexed.")
                    return []
                    
                logger.info(f"[EmailCrawler] Fetching content for {len(unindexed_ids)} new emails...")
                
                # 4. Fetch Full Content
                raw_emails = await self._batch_fetch_messages(unindexed_ids)
                
                # Update user timestamp
                user.last_indexed_timestamp = datetime.now()
                user.total_emails_indexed = (user.total_emails_indexed or 0) + len(raw_emails)
                db_session.commit()
                
                return raw_emails
                
            except (AuthenticationExpiredError, RefreshError) as e:
                self._handle_auth_failure(db_session, e)
                return []
                
                return []
                
            except Exception as e:
                if "invalid_grant" in str(e).lower():
                    self._handle_auth_failure(db_session, e)
                    return []
                    
                logger.error(f"[EmailCrawler] Error fetching delta: {e}")
                return []

    async def fetch_recent_sent_messages(self, limit: int = 20) -> List[str]:
        """
        Fetch body content of recent SENT messages for style analysis.
        """
        if not self.google_client or not self.google_client.is_available():
            return []

        try:
            # List messages from 'me'
            results = self.google_client.service.users().messages().list(
                userId='me',
                q="from:me",
                maxResults=limit
            ).execute()
            
            messages = results.get('messages', [])
            if not messages:
                return []

            msg_ids = [m['id'] for m in messages]
            
            # Fetch content
            full_messages = await self._batch_fetch_messages(msg_ids)
            
            bodies = []
            for msg in full_messages:
                # Use parser helper to get plain text body
                # We reuse internal logic or parser logic. 
                # EmailParser._extract_body is internal, let's just use what we have.
                # Actually, relying on EmailParser is cleaner but it returns a Node.
                # Let's simple extract snippet or body here to avoid overhead.
                snippet = msg.get('snippet', '')
                # Try to get full body if snippet is too short
                if len(snippet) < 50:
                    payload = msg.get('payload', {})
                    parts = [payload]
                    if 'parts' in payload:
                        parts.extend(payload['parts'])
                    
                    text = ""
                    import base64
                    for part in parts:
                        if part.get('mimeType') == 'text/plain':
                            data = part.get('body', {}).get('data', '')
                            if data:
                                try:
                                    text += base64.urlsafe_b64decode(data).decode('utf-8')
                                except Exception as e:
                                    logger.debug(f"[EmailCrawler] Base64 decode failed: {e}")
                    if text:
                        bodies.append(text)
                    else:
                        bodies.append(snippet)
                else:
                    bodies.append(snippet)

            return bodies

        except Exception as e:
            logger.warning(f"[EmailCrawler] Failed to fetch sent messages: {e}")
            return []

    def _handle_auth_failure(self, session, error: Exception):
        """Handle authentication failure by creating a user alert."""
        logger.critical(f"[EmailCrawler] Authentication expired/revoked: {error}")
        
        try:
            alert_id = f"auth_alert_{self.user_id}_google"
            
            # Check if alert already exists to avoid spamming (optional, but good practice)
            # existing = session.get(ActionableItem, alert_id)
            # if existing and existing.status == 'pending': return

            alert = ActionableItem(
                id=alert_id,
                user_id=self.user_id,
                title="Reconnect Google Account",
                item_type="system_alert",
                due_date=datetime.utcnow(),
                urgency="high",
                source_type="system",
                source_id="auth_monitor",
                suggested_action="Visit Settings to Re-authenticate",
                status="pending"
            )
            
            session.merge(alert)
            session.commit()
            logger.info(f"[EmailCrawler] Created/Updated re-auth alert: {alert_id}")
            
        except Exception as alert_err:
            logger.error(f"[EmailCrawler] Failed to create auth alert: {alert_err}")

    async def transform_item(self, item: Dict[str, Any]) -> List[ParsedNode]:
        """
        Transform a raw Gmail message dict into a list of ParsedNodes.
        (Email, Attachments, Contacts, Actions)
        """
        email_data = item
        email_id = email_data.get('id')
        if not email_id:
            return []
            
        nodes = []
        
        try:
            # 1. Parse Email Node
            email_node = await self.email_parser.parse(email_data)
            if not email_node:
                return []
            
            # CRITICAL SECURITY: Inject user_id into ALL nodes for data isolation
            # This enables filtering by user_id in graph/vector queries
            email_node.properties['user_id'] = self.user_id
            
            nodes.append(email_node)
            
            # 2. Parse Attachments
            # Download attachments content as needed since list/get may only provide ID
            attachment_nodes = await self._process_attachments(email_id, email_data)
            # Inject user_id into attachment nodes too
            for att_node in attachment_nodes:
                att_node.properties['user_id'] = self.user_id
            nodes.extend(attachment_nodes)
            
            # 3. Extract Sub-entities (Contacts, Actions)
            sub_nodes = await self._extract_sub_entities(email_node)
            # Inject user_id into all sub-entity nodes
            for sub_node in sub_nodes:
                sub_node.properties['user_id'] = self.user_id
            nodes.extend(sub_nodes)
            
            return nodes
            
        except Exception as e:
            logger.error(f"[EmailCrawler] Error parsing email {email_id}: {e}")
            return []

    async def _batch_check_indexed(self, message_ids: List[str]) -> Set[str]:
        """Check if messages are already in BOTH vector and graph stores"""
        if not message_ids:
            return set()
            
        indexed_in_vector = set()
        indexed_in_graph = set()
        
        # Doc ID format: Email_{hash(msg_id)}_chunk_0
        msg_id_map = {}
        doc_ids = []
        graph_node_ids = []
        
        for msg_id in message_ids:
            # Hash logic from EmailParser
            hash_obj = hashlib.md5(msg_id.encode())
            short_hash = hash_obj.hexdigest()[:12]
            
            base_id = f"Email_{short_hash}_chunk_0"
            doc_ids.append(base_id)
            
            graph_id = f"Email_{short_hash}"
            graph_node_ids.append(graph_id)
            
            msg_id_map[base_id] = msg_id
            msg_id_map[graph_id] = msg_id
            
        # 1. Check vector store
        if self.rag_engine and hasattr(self.rag_engine.vector_store, 'batch_document_exists'):
            try:
                found_v_ids = await asyncio.to_thread(
                    self.rag_engine.vector_store.batch_document_exists, 
                    doc_ids
                )
                for did in found_v_ids:
                    if did in msg_id_map:
                        indexed_in_vector.add(msg_id_map[did])
            except Exception as e:
                logger.warning(f"Batch vector check failed: {e}")
                
        # 2. Check graph store
        if self.graph_manager:
            try:
                # ArangoDB batch check
                found_g_ids = await self.graph_manager.get_nodes_batch(graph_node_ids)
                # found_g_ids is a dict {id: data}
                for gid in found_g_ids:
                    if gid in msg_id_map:
                        indexed_in_graph.add(msg_id_map[gid])
            except Exception as e:
                logger.warning(f"Batch graph check failed: {e}")
        
        # A message is truly "indexed" only if it's in BOTH stores 
        # (or just vector if graph is disabled)
        if self.graph_manager:
            # Must be in both
            indexed = indexed_in_vector.intersection(indexed_in_graph)
            
            # Log discrepancy if needed
            discrepancy = indexed_in_vector - indexed_in_graph
            if discrepancy:
                logger.info(f"[EmailCrawler] Found {len(discrepancy)} emails in vector store but MISSING in graph. Will re-index.")
        else:
            # Only check vector
            indexed = indexed_in_vector
        
        return indexed

    async def _batch_fetch_messages(self, message_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch full message details"""
        if hasattr(self.google_client, '_batch_get_messages_with_retry'):
            return self.google_client._batch_get_messages_with_retry(message_ids, format='full')
        return []

    async def _process_attachments(self, email_id: str, email_data: Dict[str, Any]) -> List[ParsedNode]:
        """Download and parse attachments"""
        nodes = []
        payload = email_data.get('payload', {})
        
        # Simple recursion to find parts with filenames
        parts = []
        stack = [payload]
        while stack:
            part = stack.pop()
            if part.get('filename'):
                parts.append(part)
            if 'parts' in part:
                stack.extend(part['parts'])
        
        # DEBUG: Log attachment discovery
        if parts:
            logger.info(f"[EmailCrawler] Found {len(parts)} attachments in email {email_id}: {[p.get('filename') for p in parts]}")
        
        for part in parts:
            filename = part['filename']
            body = part.get('body', {})
            att_id = body.get('attachmentId')
            
            if not att_id:
                continue
                
            # Skip calendar invites (handled by calendar crawler) and unknown formats
            if filename.lower().endswith('.ics'):
                continue

            try:
                # Download
                att_data = self.google_client.get_attachment_data(email_id, att_id)
                if not att_data:
                    continue
                    
                # Route parser
                if self._is_receipt_like(filename):
                    node = await self.receipt_parser.parse(
                        attachment_data=att_data,
                        filename=filename,
                        email_date=email_data.get('internalDate') 
                    )
                    # Add linkage properties
                    node.properties['email_id'] = email_id
                    nodes.append(node)
                    
                elif self._is_document(filename) and self.document_processor:
                    # Process for Vector RAG (Semantic Chunking)
                    await self.document_processor.process_document(
                        file_bytes=att_data,
                        filename=filename,
                        doc_id=f"{email_id}_att_{filename}",
                        metadata={'email_id': email_id}
                    )
                    
                    # Create basic Node for Graph
                    doc_node = await self.attachment_parser.parse(att_data, filename, email_id)
                    nodes.append(doc_node)
                
                else:
                    # Basic parser
                    node = await self.attachment_parser.parse(att_data, filename, email_id)
                    nodes.append(node)
                    
            except Exception as e:
                logger.warning(f"Failed attachment {filename}: {e}")
                
        return nodes

    async def _extract_sub_entities(self, email_node: ParsedNode) -> List[ParsedNode]:
        """Extract Contacts and ActionItems"""
        nodes = []
        
        # 1. Build Identity Graph (Person, Identity, KNOWS edges)
        identity_nodes = await self._build_identity_graph(email_node)
        nodes.extend(identity_nodes)
            
        # 2. Topic Extraction (Cross-App Linking)
        if self.topic_extractor:
            try:
                body_text = email_node.properties.get('body') or email_node.properties.get('content')
                if body_text and len(body_text) > 50:
                    topic_nodes = await self.topic_extractor.extract_topics(
                        content=body_text,
                        source="gmail",
                        source_node_id=email_node.node_id,
                        user_id=self.user_id
                    )
                    if topic_nodes:
                        nodes.extend(topic_nodes)
            except Exception as e:
                logger.warning(f"[EmailCrawler] Topic extraction failed: {e}")

        # 3. Action Items (LLM Extraction)
        try:
            body_text = email_node.properties.get('body', '') or email_node.properties.get('content', '')
            if body_text:
                items = await self.actionable_extractor.extract_from_text(
                    body_text, 
                    f"email:{email_node.node_id}"
                )
                
                if items:
                    with get_db_context() as session:
                        for item in items:
                            # 3.1 Persistence to SQL
                            sql_id = f"act_{hashlib.md5((item.title + email_node.node_id + 'sql').encode()).hexdigest()}"
                            
                            due_dt = None
                            if item.due_date:
                                try:
                                    due_dt = datetime.fromisoformat(item.due_date)
                                except Exception as e:
                                    logger.debug(f"[EmailCrawler] Failed to parse due_date '{item.due_date}': {e}")
                            
                            # Default to 2 days out if no date (general task)
                            if not due_dt:
                                due_dt = datetime.utcnow() + timedelta(days=2)
                                
                            act_item = ActionableItem(
                                id=sql_id,
                                user_id=self.user_id,
                                title=item.title,
                                item_type=item.item_type,
                                due_date=due_dt,
                                amount=item.amount,
                                source_type='email',
                                source_id=email_node.node_id,
                                urgency=item.urgency,
                                suggested_action=item.suggested_action
                            )
                            session.merge(act_item)
                            
                            # 3.2 Graph Node Creation
                            action_id = f"Action_{hashlib.md5((item.title + email_node.node_id).encode()).hexdigest()[:12]}"
                            
                            # Prepare relationships
                            relationships = [{
                                'from_node': email_node.node_id,
                                'to_node': action_id,
                                'rel_type': RelationType.CONTAINS.value,
                                'properties': {}
                            }]
                            
                            # 3.3 Link to Assignee (Person) if found
                            if item.assigned_to:
                                assignee_name = item.assigned_to.lower()
                                assignee_id = None
                                
                                # Skip self-assignment which is implied
                                if assignee_name not in ['me', 'myself', 'user', 'self', 'i']:
                                    # Try to match against extracted identity nodes (Sender/Recipients)
                                    for p_node in identity_nodes:
                                        if p_node.node_type != NodeType.PERSON.value:
                                            continue
                                            
                                        p_name = str(p_node.properties.get('name', '')).lower()
                                        p_email = str(p_node.properties.get('email', '')).lower()
                                        
                                        # Simple substring match
                                        if (assignee_name in p_name) or (assignee_name in p_email):
                                            assignee_id = p_node.node_id
                                            break
                                
                                if assignee_id:
                                    relationships.append({
                                        'from_node': action_id,  # Action -> Person
                                        'to_node': assignee_id,
                                        'rel_type': RelationType.ASSIGNED_TO.value,
                                        'properties': {'confidence': 0.8}
                                    })

                            action_node = ParsedNode(
                                node_id=action_id,
                                node_type=NodeType.ACTION_ITEM.value,
                                properties={
                                    'title': item.title, # Added for graph display consistency
                                    'description': item.title, 
                                    'status': 'pending', 
                                    'due_date': due_dt.isoformat(),
                                    'urgency': item.urgency,
                                    'type': item.item_type,
                                    'amount': item.amount,
                                    'assigned_to': item.assigned_to
                                },
                                relationships=relationships
                            )
                            nodes.append(action_node)
                            
                        session.commit()
        except Exception as e:
            logger.error(f"[EmailCrawler] Action items extraction failed: {e}")
            
        # 3. Financial Info / Receipts from Body
        try:
            financial_info = email_node.properties.get('financial_info')
            if financial_info and isinstance(financial_info, dict) and financial_info.get('is_receipt'):
                # Generate node ID for Receipt
                merchant = financial_info.get('merchant', 'Unknown')
                date_val = financial_info.get('date') or email_node.properties.get('date', '')
                total = financial_info.get('amount', 0.0)
                
                unique_key = f"{merchant}_{date_val}_{total}"
                receipt_id = f"Receipt_{hashlib.md5(unique_key.encode()).hexdigest()[:12]}"
                
                receipt_node = ParsedNode(
                    node_id=receipt_id,
                    node_type='Receipt',
                    properties={
                        'merchant': merchant,
                        'total': float(total),
                        'date': date_val,
                        'currency': financial_info.get('currency', 'USD'),
                        'category': financial_info.get('category', 'other'),
                        'payment_method': financial_info.get('payment_method', 'Unknown'),
                        'parsed_from': 'email_body',
                        'email_id': email_node.node_id,
                        'user_id': self.user_id
                    },
                    relationships=[{
                        'from_node': email_node.node_id,
                        'to_node': receipt_id,
                        'rel_type': RelationType.CONTAINS.value,
                        'properties': {}
                    }],
                    searchable_text=f"Receipt from {merchant} | Total: ${total} | Date: {date_val}"
                )
                nodes.append(receipt_node)
                logger.info(f"[EmailCrawler] Created Receipt node from email body: {merchant} ${total}")
                
        except Exception as e:
            logger.warning(f"[EmailCrawler] Receipt extraction from body failed: {e}")

        return nodes

    def _is_receipt_like(self, filename: str) -> bool:
        keywords = ['receipt', 'invoice', 'bill', 'payment']
        return any(k in filename.lower() for k in keywords)

    def _is_document(self, filename: str) -> bool:
        exts = ['.pdf', '.docx', '.pptx', '.txt']
        return any(filename.lower().endswith(e) for e in exts)

    async def _build_identity_graph(self, email_node: ParsedNode) -> List[ParsedNode]:
        """
        Build Person, Identity nodes and relationships from email.
        
        Creates:
        - Person node for each unique email contact
        - Identity node for their email address
        - HAS_IDENTITY relationship (Person -> Identity)
        - KNOWS relationship (User -> Person) with aliases property
        - FROM/TO/CC relationships (Email -> Person) for graph connectivity
        
        The alias is extracted from the From header: "Carol Smith" <carol@company.com>
        """
        nodes = []
        
        # Extract all email addresses from the message
        contacts_to_process = []
        
        # Sender - primary contact
        sender = email_node.properties.get('sender', '')
        if sender:
            name, email = self._parse_email_address(sender)
            if email:
                contacts_to_process.append({
                    'email': email.lower(),
                    'name': name,
                    'is_sender': True,
                    'is_cc': False
                })
        
        # Recipients (To)
        for field in ['recipients', 'to']:
            recipients = email_node.properties.get(field, [])
            if isinstance(recipients, str):
                recipients = [r.strip() for r in recipients.split(',')]
            for recipient in recipients:
                if recipient:
                    name, email = self._parse_email_address(recipient)
                    if email:
                        contacts_to_process.append({
                            'email': email.lower(),
                            'name': name,
                            'is_sender': False,
                            'is_cc': False
                        })
        
        # CC Recipients
        cc_recipients = email_node.properties.get('cc', [])
        if isinstance(cc_recipients, str):
            cc_recipients = [r.strip() for r in cc_recipients.split(',')]
        for recipient in cc_recipients:
            if recipient:
                name, email = self._parse_email_address(recipient)
                if email:
                    contacts_to_process.append({
                        'email': email.lower(),
                        'name': name,
                        'is_sender': False,
                        'is_cc': True
                    })
        
        # Track which emails we've processed to avoid duplicates
        processed_emails = set()
        
        for contact in contacts_to_process:
            email = contact['email']
            if email in processed_emails:
                continue
            processed_emails.add(email)
            
            # Check if this is the user themselves to link directly to User node
            is_user = self.user_email and email.lower() == self.user_email.lower()
            
            if is_user:
                # Link Email to User directly via SENT/RECEIVED
                if contact['is_sender']:
                    # User SENT Email
                    email_node.relationships.append({
                        'from_node': f"User/{self.user_id}",
                        'to_node': email_node.node_id,
                        'rel_type': RelationType.SENT.value,
                        'properties': {'timestamp': email_node.properties.get('date', '')}
                    })
                else:
                    # User RECEIVED Email
                    email_node.relationships.append({
                        'from_node': f"User/{self.user_id}",
                        'to_node': email_node.node_id,
                        'rel_type': RelationType.RECEIVED.value,
                        'properties': {'timestamp': email_node.properties.get('date', '')}
                    })
                # We still want to see the user in the graph, but as a User node
                # Continue if we don't want a shadow Person node for the user
                continue
            
            # 1. Create Person node with standardized ID
            from src.services.indexing.node_id_utils import generate_person_id, generate_identity_id
            person_id = generate_person_id(email=email)
            name = contact['name'] or email.split('@')[0]
            
            person_node = ParsedNode(
                node_id=person_id,
                node_type=NodeType.PERSON.value,
                properties={
                    'name': name,
                    'email': email,  # Primary email
                    'user_id': self.user_id,
                    'source': 'email'
                },
                searchable_text=f"{name} {email}"
            )
            nodes.append(person_node)
            
            # 2. Create Identity node (for the email address)
            identity_id = generate_identity_id('email', email)
            
            # Build relationships for identity node
            identity_relationships = [
                # Person HAS_IDENTITY Identity
                {
                    'from_node': person_id,
                    'to_node': identity_id,
                    'rel_type': RelationType.HAS_IDENTITY.value,
                    'properties': {'source': 'gmail'}
                }
            ]
            
            # 3. Add Email -> Person relationship (FROM, TO, or CC)
            # FIXED: Attach to email_node.relationships (not identity_relationships)
            # This ensures edges appear in graph visualization
            if contact['is_sender']:
                # Email FROM Person (sender)
                email_node.relationships.append({
                    'from_node': email_node.node_id,
                    'to_node': person_id,
                    'rel_type': RelationType.FROM.value,
                    'properties': {'timestamp': email_node.properties.get('date', '')}
                })
            elif contact['is_cc']:
                # Email CC Person
                email_node.relationships.append({
                    'from_node': email_node.node_id,
                    'to_node': person_id,
                    'rel_type': RelationType.CC.value,
                    'properties': {}
                })
            else:
                # Email TO Person (recipient)
                email_node.relationships.append({
                    'from_node': email_node.node_id,
                    'to_node': person_id,
                    'rel_type': RelationType.TO.value,
                    'properties': {}
                })
            
            identity_node = ParsedNode(
                node_id=identity_id,
                node_type=NodeType.IDENTITY.value,
                properties={
                    'type': 'email',
                    'value': email,
                    'primary': True,
                    'source': 'gmail',
                    'verified': True  # Verified since we received/sent email
                },
                relationships=identity_relationships
            )
            nodes.append(identity_node)
            
            # 4. Build pending KNOWS relationship (User -> Person with aliases)
            # The alias is the display name from the email
            if name and name != email.split('@')[0]:
                aliases = [name]
                # Also add first name as alias
                first_name = name.split()[0] if name.split() else None
                if first_name and first_name != name:
                    aliases.append(first_name)
                
                # Store as pending relationship to be created after indexing
                if not hasattr(person_node, '_pending_relationships'):
                    person_node._pending_relationships = []
                
                person_node._pending_relationships.append({
                    'rel_type': RelationType.KNOWS.value,
                    'from_id': f"User/{self.user_id}",
                    'to_id': person_id,
                    'properties': {
                        'aliases': aliases,
                        'frequency': 1,  # Will be incremented on subsequent emails
                        'source': 'gmail',
                        'is_sender': contact['is_sender']
                    }
                })
            
            # 5. COMMUNICATES_WITH edge (User → Person) — powers Personal CRM
            # Tracks interaction strength for relationship scoring and decay
            if not hasattr(person_node, '_pending_relationships'):
                person_node._pending_relationships = []
            
            person_node._pending_relationships.append({
                'rel_type': RelationType.COMMUNICATES_WITH.value,
                'from_id': f"User/{self.user_id}",
                'to_id': person_id,
                'properties': {
                    'last_interaction': email_node.properties.get('date', ''),
                    'direction': 'outbound' if not contact['is_sender'] else 'inbound',
                    'source': 'gmail',
                    'strength': 0.5  # Initial strength, reinforced by RelationshipStrengthManager
                }
            })
        
        return nodes
    
    def _parse_email_address(self, email_str: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse email string like "Carol Smith <carol@company.com>" into (name, email).
        
        Returns:
            Tuple of (name, email) or (None, None) if parsing fails
        """
        import re
        
        if not email_str:
            return None, None
        
        email_str = email_str.strip()
        
        # Pattern: "Name" <email> or Name <email>
        match = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>$', email_str)
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            return name, email
        
        # Pattern: just email@domain.com
        match = re.match(r'^([^@]+@[^@]+\.[^@]+)$', email_str)
        if match:
            email = match.group(1).strip()
            return None, email
        
        return None, None

