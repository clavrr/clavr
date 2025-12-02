"""
Intelligent Email Indexer - Production Email Indexing System

This is the primary email indexer that uses:
- Phase 1: Smart parsers (EmailParser, ReceiptParser, AttachmentParser)
- Phase 2: Knowledge Graph + Hybrid Indexing

Key features:
- Structured knowledge extraction (not just text chunks)
- Graph-based relationships between entities
- LLM-powered intent extraction
- Specialized attachment parsing (Docling integration)
- Dual indexing: Graph (structured) + Vector (semantic)

Architecture:
    Email → EmailParser → ParsedNode → HybridIndexCoordinator
                                         ↓
                              Graph DB + Vector Store
"""
import os
import asyncio
import base64
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict

from ...utils.logger import setup_logger
from ...utils.config import load_config, Config
from ...core.email.google_client import GoogleGmailClient
from ...ai.rag import RAGEngine
# Direct imports to avoid circular dependency (rag -> services.indexing.parsers -> services.indexing.indexer -> rag)
from ...ai.rag.processing.document_processor import DocumentProcessor
from ...ai.rag.processing.parser_integration import UnifiedParserRAGBridge
# Note: AttachmentProcessor removed - using AttachmentParser instead

# Phase 1 Parsers
from .parsers import EmailParser, ReceiptParser, AttachmentParser, ParsedNode

# Phase 2 Graph Integration
from .hybrid_index import HybridIndexCoordinator
from .graph import KnowledgeGraphManager, NodeType, RelationType

# Smart Indexing Mixin (optional - provides smart indexing capabilities)
try:
    from .smart_indexing import SmartIndexingMixin
    HAS_SMART_INDEXING = True
except ImportError:
    HAS_SMART_INDEXING = False
    SmartIndexingMixin = object  # Fallback to object if not available

logger = setup_logger(__name__)


class IntelligentEmailIndexer(SmartIndexingMixin if HAS_SMART_INDEXING else object):
    """
    Production email indexer with knowledge graph integration.
    
    Features:
    - Intelligent parsing with LLM-based intent extraction
    - Knowledge graph construction (entities and relationships)
    - Hybrid indexing (graph + vector)
    - Specialized attachment processing (receipts, documents)
    - ActionItem and Contact extraction
    - Periodic background sync
    
    Modes:
    - Graph Mode (recommended): Uses knowledge graph + vector store
    - Fallback Mode: Vector-only indexing if graph initialization fails
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        rag_engine: Optional[RAGEngine] = None,
        google_client: Optional[GoogleGmailClient] = None,
        llm_client: Optional[Any] = None,
        user_id: Optional[int] = None,
        collection_name: Optional[str] = None,
        use_knowledge_graph: bool = True
    ):
        """
        Initialize intelligent email indexer.
        
        Args:
            config: Configuration object
            rag_engine: RAG engine for vector indexing
            google_client: Gmail client
            llm_client: LLM client for intent extraction
            user_id: Optional user ID for per-user indexing
            collection_name: Optional collection name
            use_knowledge_graph: Enable knowledge graph mode (default: True)
        """
        self.config = config or load_config("config/config.yaml")
        self.user_id = user_id
        self.use_knowledge_graph = use_knowledge_graph
        
        # Determine collection name
        if collection_name:
            self.collection_name = collection_name
        elif user_id:
            self.collection_name = f"user_{user_id}_emails"
        else:
            self.collection_name = "email-knowledge"
        
        # Initialize RAG engine (for vector indexing)
        if rag_engine:
            self.rag_engine = rag_engine
        else:
            self.rag_engine = RAGEngine(self.config, collection_name=self.collection_name)
        
        # Gmail client
        self.google_client = google_client
        
        # Phase 1: Initialize parsers
        logger.info("Initializing Phase 1 parsers...")
        self.email_parser = EmailParser(llm_client=llm_client)
        self.receipt_parser = ReceiptParser(llm_client=llm_client)
        self.attachment_parser = AttachmentParser(llm_client=llm_client)
        
        # Initialize advanced document processing integration
        logger.info("Initializing document processing pipeline...")
        
        self.document_processor = DocumentProcessor(
            rag_engine=self.rag_engine,
            llm_client=llm_client,
            chunk_size=500,
            chunk_overlap=50,
            use_semantic_chunking=True,
            preserve_structure=True
        )
        
        # Initialize unified parser bridge for seamless integration
        self.parser_bridge = UnifiedParserRAGBridge(
            rag_engine=self.rag_engine,
            llm_client=llm_client,
            chunk_size=500,
            chunk_overlap=50
        )
        logger.info("[OK] Document processing pipeline initialized")
        
        # Phase 2: Initialize knowledge graph system
        if self.use_knowledge_graph:
            logger.info("Initializing Phase 2 knowledge graph system...")
            try:
                # Get graph configuration
                graph_config = self.config.__dict__.get('indexing', {})
                graph_backend = graph_config.get('graph_backend', 'neo4j')
                
                # Initialize graph manager
                if graph_backend == 'neo4j':
                    # Priority: environment variables > config > defaults
                    # This allows Neo4j Aura (cloud) to work via environment variables
                    import os
                    from .graph.graph_constants import NEO4J_DEFAULT_URI
                    neo4j_uri = os.getenv('NEO4J_URI') or graph_config.get('neo4j_uri') or NEO4J_DEFAULT_URI
                    neo4j_user = os.getenv('NEO4J_USER') or graph_config.get('neo4j_user') or 'neo4j'
                    neo4j_password = os.getenv('NEO4J_PASSWORD') or graph_config.get('neo4j_password') or 'password'
                    self.graph_manager = KnowledgeGraphManager(
                        backend='neo4j',
                        neo4j_uri=neo4j_uri,
                        neo4j_user=neo4j_user,
                        neo4j_password=neo4j_password,
                        config=self.config
                    )
                else:
                    # Fallback to NetworkX (in-memory)
                    self.graph_manager = KnowledgeGraphManager(backend='networkx')
                
                # Initialize hybrid coordinator
                self.hybrid_index = HybridIndexCoordinator(
                    graph_manager=self.graph_manager,
                    rag_engine=self.rag_engine
                )
                logger.info(f"[OK] Knowledge graph initialized (backend: {graph_backend})")
            except Exception as e:
                logger.warning(f"Failed to initialize knowledge graph, falling back to vector-only mode: {e}")
                self.use_knowledge_graph = False
                self.graph_manager = None
                self.hybrid_index = None
        else:
            self.graph_manager = None
            self.hybrid_index = None
            logger.info("Running in fallback mode (vector-only indexing)")
        
        # Configuration (same as legacy indexer)
        self.indexing_interval = int(os.getenv('EMAIL_INDEXING_INTERVAL', '60'))
        if self.indexing_interval < 30:
            self.indexing_interval = 30
        elif self.indexing_interval > 300:
            self.indexing_interval = 300
        
        self.inbox_interval = int(os.getenv('INBOX_INDEXING_INTERVAL', '30'))
        if self.inbox_interval < 15:
            self.inbox_interval = 15
        
        self.batch_size = 150
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._inbox_task: Optional[asyncio.Task] = None
        
        # Track last indexing time
        self.last_indexed_timestamp: Optional[datetime] = None
        self.last_inbox_check: Optional[datetime] = None
        
        # Folders to index (same as legacy)
        self.folders_to_index = [
            ("inbox", "in:inbox"),
            ("primary", "category:primary"),
            ("starred", "is:starred"),
            ("sent", "in:sent"),
            ("drafts", "in:drafts"),
            ("important", "is:important"),
            ("spam", "in:spam"),
            ("social", "category:social"),
            ("updates", "category:updates"),
            ("promotions", "category:promotions"),
            ("forums", "category:forums"),
            ("purchases", "label:purchases"),
            ("chat", "in:chats"),
        ]
        
        self.rate_limit_delay = 0.2  # 200ms between API calls
        
        logger.info(f"IntelligentEmailIndexer initialized (graph_mode: {self.use_knowledge_graph})")
    
    # ==================== PUBLIC API ====================
    
    async def start(self, initial_batch_size: int = 300):
        """
        Start background indexing loop.
        
        Args:
            initial_batch_size: Number of emails to index immediately (default: 300)
        """
        if self.is_running:
            logger.warning("Background indexer is already running")
            return
        
        if not self.rag_engine:
            logger.error("Cannot start: RAG engine not available")
            return
        
        if not self.google_client or not self.google_client.is_available():
            logger.error("Cannot start: Gmail client not available")
            return
        
        self.is_running = True
        
        # Initial bulk indexing on startup
        if initial_batch_size > 0:
            try:
                if self.google_client and hasattr(self.google_client, '_account_restricted_logged'):
                    if self.google_client._account_restricted_logged:
                        logger.info("Skipping initial indexing: Gmail API access is restricted")
                        return
                
                logger.info(f"Starting initial bulk indexing of {initial_batch_size} emails (prioritizing newer emails)...")
                # Start with recent emails first (last 30 days)
                from datetime import timedelta
                date_str = (datetime.now() - timedelta(days=30)).strftime('%Y/%m/%d')
                recent_query = f"after:{date_str}"
                indexed_count = await self._index_unindexed_emails_batch(limit=initial_batch_size, query=recent_query)
                logger.info(f"[OK] Initial indexing completed: {indexed_count} emails processed (from last 30 days)")
            except Exception as e:
                error_str = str(e)
                if 'Account Restricted' in error_str or 'access_denied' in error_str.lower():
                    if self.google_client and not hasattr(self.google_client, '_account_restricted_logged'):
                        self.google_client._account_restricted_logged = True
                    logger.info("Initial indexing stopped: Gmail API access is restricted")
                else:
                    logger.warning(f"Initial bulk indexing had errors: {e}")
        
        # Start periodic indexing loops
        self._task = asyncio.create_task(self._indexing_loop())
        self._inbox_task = asyncio.create_task(self._inbox_indexing_loop())
        
        mode_str = "graph + vector" if self.use_knowledge_graph else "vector only"
        logger.info(f"Background email indexing started ({mode_str}):")
        logger.info(f"  - All folders: every {self.indexing_interval}s")
        logger.info(f"  - Inbox (fast): every {self.inbox_interval}s")
    
    async def stop(self):
        """Stop background indexing loop."""
        self.is_running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._inbox_task:
            self._inbox_task.cancel()
            try:
                await self._inbox_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Background email indexing stopped")
    
    def set_rag_engine(self, rag_engine: RAGEngine):
        """Set or update RAG engine."""
        self.rag_engine = rag_engine
        if self.hybrid_index:
            self.hybrid_index.rag_engine = rag_engine
        logger.info("RAG engine updated for intelligent indexer")
    
    def set_google_client(self, google_client: GoogleGmailClient):
        """Set or update Gmail client."""
        self.google_client = google_client
        logger.info("Gmail client updated for intelligent indexer")
    
    # ==================== INDEXING CORE ====================
    
    async def index_email(self, email_data: Any) -> bool:
        """
        Index a single email using intelligent parsing.
        
        This is the main entry point that chooses between:
        - Graph mode: Parse → Extract entities → Index in graph + vector
        - Fallback mode: Simple text indexing (vector only)
        
        Args:
            email_data: Raw email data from Gmail API (dict expected, but validated at runtime)
            
        Returns:
            True if indexing succeeded, False otherwise
        """
        # Validate email_data is a dictionary (defensive check)
        if not email_data:
            logger.warning(f"Invalid email_data in index_email: None or empty")
            return False
        
        if isinstance(email_data, list):
            logger.error(f"CRITICAL: Received list instead of dict in index_email. List length: {len(email_data)}. This should never happen!")
            return False
        
        if not isinstance(email_data, dict):
            logger.warning(f"Invalid email_data type: {type(email_data)}, expected dict. Skipping.")
            return False
        
        if self.use_knowledge_graph and self.hybrid_index:
            return await self._index_with_graph(email_data)
        else:
            return await self._index_vector_only(email_data)
    
    async def _index_with_graph(self, email_data: Dict[str, Any]) -> bool:
        """
        Index email using knowledge graph approach (Phase 1 + Phase 2).
        
        Flow:
        1. Parse email with EmailParser → get ParsedNode
        2. Parse attachments (receipts, documents) → get more ParsedNodes
        3. Extract sub-entities (ActionItems, Contacts) → create nodes
        4. Index all nodes in hybrid system (graph + vector)
        """
        # Validate email_data is a dictionary (defensive check)
        if not email_data:
            logger.warning(f"Invalid email_data in _index_with_graph: None or empty")
            return False
        
        if isinstance(email_data, list):
            logger.error(f"CRITICAL: Received list instead of dict in _index_with_graph. List length: {len(email_data)}. This should never happen!")
            return False
        
        if not isinstance(email_data, dict):
            logger.warning(f"Invalid email_data in _index_with_graph: {type(email_data)}, expected dict")
            return False
        
        try:
            email_id = email_data.get('id', '')
            if not email_id:
                logger.warning("Email data missing 'id' field")
                return False
            
            # Check if already indexed (use same node ID format as EmailParser)
            email_node_id = self.email_parser.generate_node_id('Email', email_id)
            # Emails are stored as chunks, so check for first chunk
            first_chunk_id = f"{email_node_id}_chunk_0"
            if self.rag_engine.vector_store.document_exists(first_chunk_id):
                return True
            
            # Stage 1: Parse email with EmailParser
            logger.debug(f"Parsing email {email_id[:20]} with EmailParser...")
            email_node = await self.email_parser.parse(email_data)
            
            # Stage 2: Parse attachments
            attachment_nodes = []
            if email_data.get('has_attachments'):
                attachment_nodes = await self._parse_attachments_with_specialized_parsers(
                    email_id, email_data
                )
                # Add attachment relationships to email node
                for att_node in attachment_nodes:
                    email_node.relationships.append({
                        'from_node': email_node.node_id,
                        'to_node': att_node.node_id,
                        'rel_type': RelationType.HAS_ATTACHMENT.value,
                        'properties': {}
                    })
            
            # Stage 3: Index email node in hybrid system
            logger.debug(f"Indexing email {email_id[:20]} in hybrid system...")
            success_count, failed_count = await self.hybrid_index.index_batch([email_node])
            
            # Stage 4: Index attachment nodes
            if attachment_nodes:
                att_success, att_failed = await self.hybrid_index.index_batch(attachment_nodes)
                success_count += att_success
                failed_count += att_failed
            
            # Stage 5: Extract and index sub-entities
            await self._extract_and_index_sub_entities(email_node)
            
            if failed_count > 0:
                logger.warning(f"Email {email_id[:20]}: {success_count} nodes indexed, {failed_count} failed")
            else:
                logger.debug(f"[OK] Email {email_id[:20]} indexed ({success_count} nodes)")
            
            return success_count > 0
            
        except Exception as e:
            # Check if it's a connection error (Neo4j unavailable)
            error_str = str(e)
            is_connection_error = (
                "Cannot resolve address" in error_str or
                "nodename nor servname" in error_str.lower() or
                "Connection refused" in error_str or
                "ServiceUnavailable" in error_str or
                "Couldn't connect" in error_str
            )
            
            if is_connection_error:
                # Neo4j is unavailable - log briefly and fallback gracefully
                logger.debug(f"Neo4j unavailable, using vector-only indexing for email {email_data.get('id', 'unknown')[:20]}")
            else:
                # Other errors - log with full details
                logger.error(f"Failed to index email with graph: {e}", exc_info=True)
            
            # Fallback to vector-only indexing
            logger.info("Falling back to vector-only indexing...")
            return await self._index_vector_only(email_data)
    
    async def _parse_attachments_with_specialized_parsers(
        self, email_id: str, email_data: Dict[str, Any]
    ) -> List[ParsedNode]:
        """
        Parse attachments using specialized parsers.
        
        Routes each attachment to the appropriate parser:
        - Receipts/invoices → ReceiptParser (Docling)
        - PDFs/documents → AttachmentParser (Docling)
        
        Returns:
            List of ParsedNode objects for attachments
        """
        if not self.google_client or not self.google_client.is_available():
            return []
        
        attachment_nodes = []
        
        try:
            # Get full message with attachments
            message = self.google_client.service.users().messages().get(
                userId='me',
                id=email_id,
                format='full'
            ).execute()
            
            payload = message.get('payload', {})
            
            # Extract attachment data
            def extract_attachment_parts(parts):
                """Recursively extract attachments."""
                attachments = []
                for part in parts:
                    if part.get('filename'):
                        attachment_id = part['body'].get('attachmentId')
                        if attachment_id:
                            try:
                                att = self.google_client.service.users().messages().attachments().get(
                                    userId='me',
                                    messageId=email_id,
                                    id=attachment_id
                                ).execute()
                                
                                attachment_data = base64.urlsafe_b64decode(att['data'])
                                filename = part.get('filename', 'unknown')
                                attachments.append((filename, attachment_data))
                            except Exception as e:
                                logger.warning(f"Failed to download attachment {part.get('filename')}: {e}")
                    
                    # Recurse into nested parts
                    if 'parts' in part:
                        attachments.extend(extract_attachment_parts(part['parts']))
                
                return attachments
            
            # Get all attachment parts
            if 'parts' in payload:
                all_attachments = extract_attachment_parts(payload['parts'])
            else:
                all_attachments = []
            
            # Parse each attachment with appropriate parser
            for filename, attachment_data in all_attachments:
                try:
                    # Route to appropriate parser based on file type
                    if self._is_receipt_like(filename):
                        # Use ReceiptParser for receipts/invoices
                        # Pass email_date to parser so it can use it as fallback for receipt date
                        email_date = email_data.get('date', '')
                        node = await self.receipt_parser.parse(
                            attachment_data=attachment_data,
                            filename=filename,
                            email_date=email_date
                        )
                        # Add email context to node properties
                        node.properties['email_id'] = email_id
                        node.properties['email_subject'] = email_data.get('subject', '')
                        node.properties['email_sender'] = email_data.get('sender', '')
                        node.properties['email_date'] = email_date
                        
                        attachment_nodes.append(node)
                        logger.debug(f"Parsed receipt: {filename}")
                    
                    elif self._is_document(filename):
                        # Use advanced document processor for better parsing
                        # This uses Docling + semantic chunking for optimal results
                        try:
                            result = await self.document_processor.process_document(
                                file_bytes=attachment_data,
                                filename=filename,
                                doc_id=f"{email_id}_att_{filename}",
                                metadata={
                                    'email_id': email_id,
                                    'email_subject': email_data.get('subject', ''),
                                    'email_sender': email_data.get('sender', ''),
                                    'email_date': email_data.get('date', ''),
                                    'source': 'email_attachment',
                                    'doc_type': 'attachment'
                                }
                            )
                            logger.debug(
                                f"Processed document with DocumentProcessor: {filename} "
                                f"({result['num_chunks']} chunks, {result['num_tables']} tables)"
                            )
                            # Document already indexed via document_processor
                            # No need to create ParsedNode - already in vector store
                            
                        except Exception as doc_proc_error:
                            # Fallback to basic AttachmentParser if advanced processing fails
                            logger.warning(
                                f"DocumentProcessor failed for {filename}, "
                                f"falling back to basic parser: {doc_proc_error}"
                            )
                            node = await self.attachment_parser.parse(
                                attachment_data=attachment_data,
                                filename=filename,
                                email_id=None,
                                metadata={'email_id': email_id}
                            )
                            attachment_nodes.append(node)
                            logger.debug(f"Parsed document (fallback): {filename}")
                    
                except Exception as e:
                    logger.warning(f"Failed to parse attachment {filename}: {e}")
            
        except Exception as e:
            logger.error(f"Failed to extract attachments from email {email_id[:20]}: {e}")
        
        return attachment_nodes
    
    def _is_receipt_like(self, filename: str) -> bool:
        """Check if filename indicates a receipt/invoice."""
        receipt_keywords = ['receipt', 'invoice', 'statement', 'bill', 'payment', 'transaction']
        filename_lower = filename.lower()
        return any(keyword in filename_lower for keyword in receipt_keywords)
    
    def _is_document(self, filename: str) -> bool:
        """Check if filename is a parseable document."""
        doc_extensions = ['.pdf', '.docx', '.doc', '.pptx', '.xlsx', '.xls', '.txt']
        filename_lower = filename.lower()
        return any(filename_lower.endswith(ext) for ext in doc_extensions)
    
    async def _extract_and_index_sub_entities(self, email_node: ParsedNode):
        """
        Extract and index sub-entities from email node.
        
        Creates additional nodes for:
        - ActionItems (tasks mentioned in email)
        - Contacts (sender, recipients)
        - Topics (subjects discussed)
        """
        try:
            sub_nodes = []
            
            # Extract ActionItems from intents
            if 'intents' in email_node.properties:
                intents_data = email_node.properties['intents']
                # Parse JSON string if needed (intents is stored as JSON string)
                if isinstance(intents_data, str):
                    try:
                        intents_data = json.loads(intents_data) if intents_data else {}
                    except (json.JSONDecodeError, TypeError, ValueError):
                        intents_data = {}
                elif not isinstance(intents_data, dict):
                    # Handle None or other unexpected types
                    intents_data = {}
                action_items = intents_data.get('action_items', []) if isinstance(intents_data, dict) else []
                
                for i, action_desc in enumerate(action_items):
                    action_node = ParsedNode(
                        node_id=f"Action_{email_node.node_id}_{i}",
                        node_type=NodeType.ACTION_ITEM.value,
                        properties={
                            'description': action_desc,
                            'status': 'pending',
                            'source_email': email_node.node_id,
                            'created_at': email_node.properties.get('date', datetime.now().isoformat())
                        },
                        relationships=[
                            {
                                'from_node': email_node.node_id,
                                'to_node': f"Action_{email_node.node_id}_{i}",
                                'rel_type': RelationType.CONTAINS.value,
                                'properties': {}
                            }
                        ]
                    )
                    sub_nodes.append(action_node)
            
            # Extract Contact nodes
            sender_email = email_node.properties.get('sender', '')
            if sender_email:
                contact_node = self._create_contact_node(sender_email, email_node.node_id)
                if contact_node:
                    sub_nodes.append(contact_node)
            
            # Index sub-entities
            if sub_nodes:
                success, failed = await self.hybrid_index.index_batch(sub_nodes)
                logger.debug(f"Indexed {success} sub-entities for email {email_node.node_id[:20]}")
        
        except Exception as e:
            logger.warning(f"Failed to extract sub-entities: {e}")
    
    def _create_contact_node(self, email_address: str, source_email_id: str) -> Optional[ParsedNode]:
        """Create a Contact node from an email address."""
        try:
            import re
            
            # Extract email address from formats like:
            # - "Name <email@domain.com>"
            # - "email@domain.com"
            # - "Name email@domain.com"
            email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            email_match = re.search(email_pattern, email_address)
            
            if not email_match:
                logger.debug(f"Could not extract email address from: {email_address}")
                return None
            
            actual_email = email_match.group(1).lower().strip()
            
            # Extract name from the sender string if present
            name = None
            if '<' in email_address:
                # Format: "Name <email@domain.com>"
                name = email_address.split('<')[0].strip()
                if not name or name == actual_email:
                    name = actual_email.split('@')[0].replace('.', ' ').title()
            else:
                # Just email address, derive name from email
                name = actual_email.split('@')[0].replace('.', ' ').title()
            
            # Clean up name
            if name:
                name = name.strip('"\'')
                if not name or name == actual_email:
                    name = actual_email.split('@')[0].replace('.', ' ').title()
            
            # Format datetime for schema validation (use DATETIME_FORMAT: %Y-%m-%dT%H:%M:%S)
            last_contact_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            
            # Build searchable text for vector indexing
            searchable_parts = []
            if name:
                searchable_parts.append(f"Contact: {name}")
            searchable_parts.append(f"Email: {actual_email}")
            searchable_text = " | ".join(searchable_parts)
            
            contact_node = ParsedNode(
                node_id=f"Contact_{actual_email}",
                node_type=NodeType.CONTACT.value,
                properties={
                    'email': actual_email,  # Use extracted email, not the full string
                    'name': name,
                    'last_contact': last_contact_str
                },
                relationships=[
                    {
                        'from_node': source_email_id,
                        'to_node': f"Contact_{actual_email}",
                        'rel_type': RelationType.FROM.value,
                        'properties': {}
                    }
                ],
                searchable_text=searchable_text
            )
            return contact_node
        except Exception as e:
            logger.debug(f"Failed to create contact node: {e}")
            return None
    
    async def _index_vector_only(self, email_data: Dict[str, Any]) -> bool:
        """
        Enhanced fallback indexing mode using UnifiedParserRAGBridge.
        
        This mode:
        1. Uses EmailParser for better structure extraction
        2. Applies email-aware chunking via parser_bridge
        3. Processes attachments with DocumentProcessor
        4. Indexes everything in vector store with rich metadata
        
        This provides much better search quality than the old flat text approach.
        """
        # Validate email_data is a dictionary
        if not email_data or not isinstance(email_data, dict):
            logger.warning(f"Invalid email_data in _index_vector_only: {type(email_data)}, expected dict")
            return False
        
        try:
            email_id = email_data.get('id', '')
            if not email_id:
                return False
            
            # Check if already indexed (use same node ID format as EmailParser)
            import hashlib
            hash_obj = hashlib.md5(email_id.encode())
            short_hash = hash_obj.hexdigest()[:12]
            email_node_id = f"Email_{short_hash}"
            # Emails are stored as chunks, so check for first chunk
            first_chunk_id = f"{email_node_id}_chunk_0"
            if self.rag_engine.vector_store.document_exists(first_chunk_id):
                return True
            
            # Use UnifiedParserRAGBridge for intelligent email indexing
            # This applies email-aware chunking and better metadata extraction
            try:
                result = await self.parser_bridge.index_email(
                    email_data=email_data,
                    email_id=email_id
                )
                logger.debug(
                    f"[OK] Email indexed via parser_bridge: {email_id[:20]} "
                    f"({result['num_chunks']} chunks, intent: {result.get('parsed_intent', 'unknown')})"
                )
                
                # Process attachments separately if present
                if email_data.get('has_attachments'):
                    await self._process_attachments_enhanced(email_id, email_data)
                
                return True
                
            except Exception as bridge_error:
                # Fallback to basic indexing if parser_bridge fails
                logger.warning(
                    f"Parser bridge failed for {email_id[:20]}, "
                    f"using basic fallback: {bridge_error}"
                )
                return await self._index_vector_only_basic(email_data)
            
        except Exception as e:
            logger.warning(f"Failed to index email (enhanced mode): {e}")
            return False
    
    async def _index_vector_only_basic(self, email_data: Dict[str, Any]) -> bool:
        """
        Basic fallback indexing (original implementation).
        
        Used only when enhanced indexing fails.
        """
        try:
            email_id = email_data.get('id', '')
            if not email_id:
                return False
            
            # Prepare content for indexing
            subject = email_data.get('subject', '')
            sender = email_data.get('sender', '')
            body = email_data.get('body', '')
            timestamp = email_data.get('date', '')
            folder = email_data.get('folder', 'inbox')
            has_attachments = email_data.get('has_attachments', False)
            
            if not subject and not body:
                return False
            
            content_parts = []
            if subject:
                content_parts.append(f"Subject: {subject}")
            if sender:
                content_parts.append(f"From: {sender}")
            if body:
                body_snippet = body[:1500] if len(body) > 1500 else body
                content_parts.append(f"Content: {body_snippet}")
            
            content = "\n\n".join(content_parts)
            
            # Create metadata
            labels = email_data.get('labels', [])
            metadata = {
                "subject": subject,
                "sender": sender,
                "sender_domain": sender.split('@')[1] if '@' in sender else None,
                "timestamp": timestamp,
                "folder": folder,
                "message_id": email_id,
                "thread_id": email_data.get('threadId', ''),
                "has_attachments": has_attachments,
                "read": "UNREAD" not in labels,
                "important": "IMPORTANT" in labels,
                "starred": "STARRED" in labels,
                "labels": ", ".join(labels) if labels else None,
                "indexed_at": datetime.now().isoformat(),
                "indexed_by": "basic_fallback",
                "doc_type": "email",
                "neo4j_node_id": email_id,  # ← THE BRIDGE: Links to graph 
                "node_id": email_id  # Also keep for backward compatibility
            }
            
            # Index in vector store
            self.rag_engine.index_document(email_id, content, metadata)
            logger.debug(f"[OK] Basic indexed email {email_id[:20]}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed basic indexing: {e}")
            return False
    
    async def _process_attachments_enhanced(self, email_id: str, email_data: Dict[str, Any]):
        """
        Process email attachments using DocumentProcessor for better extraction.
        
        This method downloads attachments and uses the advanced document processing
        pipeline (Docling + semantic chunking) for optimal indexing.
        """
        if not self.google_client or not self.google_client.is_available():
            return
        
        try:
            message = self.google_client.service.users().messages().get(
                userId='me',
                id=email_id,
                format='full'
            ).execute()
            
            payload = message.get('payload', {})
            
            # Extract attachment data
            def extract_attachment_parts(parts):
                """Recursively extract attachments."""
                attachments = []
                for part in parts:
                    if part.get('filename'):
                        attachment_id = part['body'].get('attachmentId')
                        if attachment_id:
                            try:
                                att = self.google_client.service.users().messages().attachments().get(
                                    userId='me',
                                    messageId=email_id,
                                    id=attachment_id
                                ).execute()
                                
                                attachment_data = base64.urlsafe_b64decode(att['data'])
                                filename = part.get('filename', 'unknown')
                                attachments.append((filename, attachment_data))
                            except Exception as e:
                                logger.warning(f"Failed to download attachment {part.get('filename')}: {e}")
                    
                    if 'parts' in part:
                        attachments.extend(extract_attachment_parts(part['parts']))
                
                return attachments
            
            # Get all attachments
            if 'parts' in payload:
                all_attachments = extract_attachment_parts(payload['parts'])
            else:
                return
            
            # Process each attachment
            for filename, attachment_data in all_attachments:
                if not self._is_document(filename):
                    continue
                
                try:
                    # Use DocumentProcessor for advanced parsing
                    result = await self.document_processor.process_document(
                        file_bytes=attachment_data,
                        filename=filename,
                        doc_id=f"{email_id}_att_{filename}",
                        metadata={
                            'email_id': email_id,
                            'email_subject': email_data.get('subject', ''),
                            'email_sender': email_data.get('sender', ''),
                            'email_date': email_data.get('date', ''),
                            'source': 'email_attachment',
                            'doc_type': 'attachment'
                        }
                    )
                    logger.debug(
                        f"Processed attachment: {filename} "
                        f"({result['num_chunks']} chunks, {result.get('num_tables', 0)} tables)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to process attachment {filename}: {e}")
                    
        except Exception as e:
            logger.warning(f"Failed to process attachments for {email_id}: {e}")
    
    async def _extract_attachment_contents_fallback(self, email_id: str) -> List[Tuple[str, str]]:
        """
        Fallback attachment extraction using AttachmentProcessor.
        
        Used when specialized parsers fail or in fallback mode.
        """
        if not self.google_client or not self.google_client.is_available():
            return []
        
        try:
            message = self.google_client.service.users().messages().get(
                userId='me',
                id=email_id,
                format='full'
            ).execute()
            
            payload = message.get('payload', {})
            attachments_data = []
            
            async def extract_attachments_from_parts(parts):
                for part in parts:
                    if part.get('filename'):
                        attachment_id = part['body'].get('attachmentId')
                        if attachment_id:
                            try:
                                att = self.google_client.service.users().messages().attachments().get(
                                    userId='me',
                                    messageId=email_id,
                                    id=attachment_id
                                ).execute()
                                
                                attachment_data = base64.urlsafe_b64decode(att['data'])
                                filename = part.get('filename', 'unknown')
                                
                                # Use AttachmentParser to extract text (async method)
                                try:
                                    parsed_node = await self.attachment_parser.parse(
                                        attachment_data, filename
                                    )
                                    extracted_text = parsed_node.searchable_text if parsed_node else None
                                except Exception:
                                    # Fallback: try to decode as text if it's a text file
                                    if filename.endswith(('.txt', '.md', '.csv')):
                                        try:
                                            extracted_text = attachment_data.decode('utf-8', errors='ignore')
                                        except Exception:
                                            extracted_text = None
                                    else:
                                        extracted_text = None
                                
                                if extracted_text:
                                    attachments_data.append((filename, extracted_text))
                                
                            except Exception as e:
                                logger.warning(f"Failed to extract attachment {part.get('filename')}: {e}")
                    
                    if 'parts' in part:
                        await extract_attachments_from_parts(part['parts'])
            
            if 'parts' in payload:
                await extract_attachments_from_parts(payload['parts'])
            
            return attachments_data
            
        except Exception as e:
            logger.error(f"Failed to extract attachments (fallback): {e}")
            return []
    
    # ==================== PERIODIC SYNC ====================
    
    async def _indexing_loop(self):
        """Main indexing loop for all folders."""
        while self.is_running:
            try:
                if self.user_id:
                    await self._refresh_token_if_needed()
                
                if self.google_client and hasattr(self.google_client, '_account_restricted_logged'):
                    if self.google_client._account_restricted_logged:
                        await asyncio.sleep(self.indexing_interval * 2)
                        continue
                
                await self._index_unindexed_emails(exclude_inbox=True)
                self.last_indexed_timestamp = datetime.now()
                
                await asyncio.sleep(self.indexing_interval)
            except asyncio.CancelledError:
                logger.info("Background indexing cancelled")
                break
            except Exception as e:
                logger.error(f"Error in background indexing loop: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def _inbox_indexing_loop(self):
        """Fast indexing loop for inbox only."""
        await asyncio.sleep(5)  # Initial delay
        
        while self.is_running:
            try:
                if self.user_id:
                    await self._refresh_token_if_needed()
                
                if self.google_client and hasattr(self.google_client, '_account_restricted_logged'):
                    if self.google_client._account_restricted_logged:
                        await asyncio.sleep(self.inbox_interval * 2)
                        continue
                
                await self._index_inbox_emails()
                self.last_inbox_check = datetime.now()
                
                await asyncio.sleep(self.inbox_interval)
            except asyncio.CancelledError:
                logger.info("Inbox indexing cancelled")
                break
            except Exception as e:
                logger.error(f"Error in inbox indexing loop: {e}", exc_info=True)
                await asyncio.sleep(30)
    
    async def _index_unindexed_emails(self, exclude_inbox: bool = False):
        """Index unindexed emails from all folders."""
        if not self.google_client or not self.google_client.is_available():
            return
        
        for folder_name, folder_query in self.folders_to_index:
            if exclude_inbox and folder_name == "inbox":
                continue
            
            try:
                unindexed_list, _ = await self._get_unindexed_emails(folder_query, max_results=self.batch_size)
                if unindexed_list:
                    logger.info(f"Found {len(unindexed_list)} unindexed emails in {folder_name}")
                    for email in unindexed_list:
                        # Validate email is a dictionary before indexing
                        if not isinstance(email, dict):
                            logger.warning(f"Skipping invalid email in {folder_name}: expected dict, got {type(email)}")
                            continue
                        await self.index_email(email)
                        await asyncio.sleep(self.rate_limit_delay)
            except Exception as e:
                logger.error(f"Error indexing {folder_name}: {e}")
    
    async def _index_inbox_emails(self):
        """Fast indexing for inbox only."""
        try:
            unindexed_list, _ = await self._get_unindexed_emails("in:inbox", max_results=50)
            if unindexed_list:
                logger.info(f"Found {len(unindexed_list)} unindexed emails in inbox")
                for email in unindexed_list:
                    # Validate email is a dictionary before indexing
                    if not isinstance(email, dict):
                        logger.warning(f"Skipping invalid email in inbox: expected dict, got {type(email)}")
                        continue
                    await self.index_email(email)
                    await asyncio.sleep(self.rate_limit_delay)
        except Exception as e:
            logger.error(f"Error indexing inbox: {e}")
    
    async def _index_unindexed_emails_batch(self, limit: int = 300, page_token: Optional[str] = None, query: str = "in:all") -> Tuple[int, Optional[str]]:
        """
        Index a batch of unindexed emails (for initial sync).
        
        Args:
            limit: Maximum number of emails to index in this batch
            page_token: Gmail API page token for pagination
            query: Gmail search query (default: "in:all")
        
        Returns:
            Tuple of (indexed_count, next_page_token)
            - indexed_count: Number of emails successfully indexed
            - next_page_token: Gmail API page token for next batch (None if no more pages)
        """
        if not self.google_client or not self.google_client.is_available():
            return (0, None)
        
        indexed_count = 0
        next_token = None
        try:
            unindexed, next_token = await self._get_unindexed_emails(query, max_results=limit, page_token=page_token)
            total_emails = len(unindexed)
            logger.info(f"Indexing batch of {total_emails} emails... (next_token={'yes' if next_token else 'no'})")
            
            # Don't update progress here - let the calling function handle overall progress
            # This function just processes a batch and returns the count
            
            for i, email in enumerate(unindexed, 1):
                try:
                    # Validate email is a dictionary before indexing
                    if not isinstance(email, dict):
                        logger.warning(f"Skipping invalid email at index {i}: expected dict, got {type(email)}")
                        continue
                    
                    success = await self.index_email(email)
                    if success:
                        indexed_count += 1
                    
                    # Log progress every 10 emails (but don't update DB - caller handles that)
                    if i % 10 == 0 or i == total_emails:
                        logger.info(f"Batch progress: {i}/{total_emails} emails processed ({indexed_count} successfully indexed)")
                    
                    await asyncio.sleep(self.rate_limit_delay)
                except Exception as e:
                    logger.warning(f"Failed to index email in batch: {e}")
            
        except Exception as e:
            logger.error(f"Error in batch indexing: {e}")
        
        return (indexed_count, next_token)
    
    async def _update_indexing_progress(self, current: int, total: int, indexed_count: int):
        """Update indexing progress in database."""
        if not self.user_id or total == 0:
            return
        
        try:
            from ...database import get_db_context
            from ...database.models import User
            
            with get_db_context() as db:
                user = db.query(User).filter(User.id == self.user_id).first()
                if user:
                    progress_percent = (current / total) * 100.0
                    user.indexing_progress_percent = progress_percent
                    user.total_emails_indexed = indexed_count
                    user.indexing_status = 'in_progress'
                    db.commit()
        except Exception as e:
            logger.debug(f"Failed to update indexing progress: {e}")
    
    async def _get_unindexed_emails(self, query: str, max_results: int = 100, page_token: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Get list of emails that haven't been indexed yet.
        
        NOTE: This method uses Gmail API because it's part of the INDEXING process.
        We need to fetch emails from Gmail to index them into Pinecone/Neo4j.
        This is different from retrieval/search, which uses indexed data first.
        
        For email retrieval/search, see EmailService.search_emails() which:
        1. First queries indexed data (Pinecone + Neo4j)
        2. Only falls back to Gmail API if index doesn't have enough results
        
        Args:
            query: Gmail search query
            max_results: Maximum number of messages to fetch from Gmail API
            page_token: Optional page token for pagination
            
        Returns:
            Tuple of (unindexed_emails_list, next_page_token)
            - unindexed_emails_list: List of email data dictionaries
            - next_page_token: Gmail API page token for next page (None if no more pages)
        """
        if not self.google_client or not self.google_client.is_available():
            logger.warning("Gmail client not available for fetching emails")
            return ([], None)
        
        try:
            import time
            logger.info(f"[_get_unindexed] Fetching emails from Gmail with query: {query}, max_results: {max_results}, page_token={'yes' if page_token else 'no'}")
            gmail_start = time.time()
            
            # List messages matching query with pagination
            # Gmail API returns messages in reverse chronological order (newest first) by default
            # We ensure this by not specifying an orderBy parameter (defaults to date descending)
            request_params = {
                'userId': 'me',
                'q': query,
                'maxResults': max_results
                # Note: Gmail API doesn't support explicit sorting, but defaults to newest first
            }
            if page_token:
                request_params['pageToken'] = page_token
                
            logger.debug(f"[_get_unindexed] Calling Gmail API list()...")
            results = self.google_client.service.users().messages().list(**request_params).execute()
            gmail_time = time.time() - gmail_start
            logger.info(f"[_get_unindexed] Gmail API list() completed in {gmail_time:.2f}s")
            
            messages = results.get('messages', [])
            next_page_token = results.get('nextPageToken')  # Get pagination token
            logger.info(f"Gmail API returned {len(messages)} messages (next_page_token={'yes' if next_page_token else 'no'})")
            if not messages:
                # This is normal - query might not match any emails (empty folder, all indexed, etc.)
                logger.debug(f"No messages returned from Gmail API for query: {query}")
                return ([], None)
            
            # Get full message details
            unindexed = []
            # Use batch check for efficiency (much faster than individual checks)
            message_ids = [msg['id'] for msg in messages]
            logger.info(f"Batch checking {len(message_ids)} emails for indexed status...")
            
            # Use the batch check method from SmartIndexingMixin if available
            # Add timeout to prevent hanging
            import asyncio
            try:
                if hasattr(self, '_batch_check_indexed'):
                    logger.info(f"Using _batch_check_indexed method for batch checking {len(message_ids)} emails...")
                    batch_check_start = time.time()
                    # Add timeout to batch check - more reasonable calculation:
                    # - Minimum 10 seconds for small batches (Pinecone API latency)
                    # - 200ms per email for larger batches
                    # - Maximum 120 seconds for very large batches
                    timeout_seconds = max(10.0, min(120.0, len(message_ids) * 0.2))
                    logger.debug(f"Batch check timeout set to {timeout_seconds:.1f}s for {len(message_ids)} emails")
                    already_indexed_set = await asyncio.wait_for(
                        self._batch_check_indexed(message_ids),
                        timeout=timeout_seconds
                    )
                    batch_check_time = time.time() - batch_check_start
                    already_indexed = len(already_indexed_set)
                    unindexed_ids = [mid for mid in message_ids if mid not in already_indexed_set]
                    logger.info(f"Batch check complete in {batch_check_time:.2f}s: {len(unindexed_ids)} unindexed, {already_indexed} already indexed")
                else:
                    logger.warning("_batch_check_indexed not available, using fallback individual checks")
                    # Fallback: check individually (slow but works)
                    import hashlib
                    already_indexed_set = set()
                    unindexed_ids = []
                    for idx, msg_id in enumerate(message_ids):
                        if idx % 50 == 0:
                            logger.debug(f"Checking email {idx+1}/{len(message_ids)}...")
                        hash_obj = hashlib.md5(msg_id.encode())
                        short_hash = hash_obj.hexdigest()[:12]
                        email_node_id = f"Email_{short_hash}"
                        first_chunk_id = f"{email_node_id}_chunk_0"
                        if self.rag_engine.vector_store.document_exists(first_chunk_id):
                            already_indexed_set.add(msg_id)
                        else:
                            unindexed_ids.append(msg_id)
                    already_indexed = len(already_indexed_set)
                    logger.info(f"Individual check complete: {len(unindexed_ids)} unindexed, {already_indexed} already indexed")
            except asyncio.TimeoutError:
                # Calculate what the timeout was (same logic as above)
                timeout_seconds = max(10.0, min(120.0, len(message_ids) * 0.2))
                logger.warning(f"Batch check timed out after {timeout_seconds:.1f}s for {len(message_ids)} emails. This may indicate slow Pinecone API response.")
                logger.info(f"Falling back to processing all {len(message_ids)} emails (assuming unindexed). This is safe but may re-index already indexed emails.")
                unindexed_ids = message_ids
                already_indexed = 0
            except Exception as e:
                logger.error(f"Error during batch check: {e}", exc_info=True)
                logger.error(f"Falling back to processing all {len(message_ids)} emails (assuming unindexed)")
                unindexed_ids = message_ids
                already_indexed = 0
            
            # Fetch full messages for unindexed emails only
            for msg_id in unindexed_ids:
                try:
                    full_msg = self.google_client.service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='full'
                    ).execute()
                    
                    # Parse message data
                    email_data = self._parse_gmail_message(full_msg)
                    unindexed.append(email_data)
                    
                except Exception as e:
                    logger.warning(f"Failed to fetch message {msg_id}: {e}")
            
            logger.info(f"Found {len(unindexed)} unindexed emails ready to index (out of {len(messages)} total, {already_indexed} already indexed)")
            return (unindexed, next_page_token)
            
        except Exception as e:
            logger.error(f"Failed to get unindexed emails: {e}", exc_info=True)
            return ([], None)
    
    def _parse_gmail_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Gmail API message into standardized format."""
        headers = {h['name'].lower(): h['value'] for h in message['payload'].get('headers', [])}
        
        # Extract body
        body = ''
        if 'parts' in message['payload']:
            for part in message['payload']['parts']:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
        elif 'body' in message['payload'] and 'data' in message['payload']['body']:
            body = base64.urlsafe_b64decode(message['payload']['body']['data']).decode('utf-8', errors='ignore')
        
        return {
            'id': message['id'],
            'threadId': message['threadId'],
            'subject': headers.get('subject', ''),
            'sender': headers.get('from', ''),
            'to': headers.get('to', ''),
            'date': headers.get('date', ''),
            'body': body,
            'labels': message.get('labelIds', []),
            'has_attachments': any(
                part.get('filename') for part in message['payload'].get('parts', [])
            ) if 'parts' in message['payload'] else False,
            'folder': 'inbox'  # Simplified
        }
    
    async def _refresh_token_if_needed(self):
        """Refresh OAuth token if needed (for per-user indexers)."""
        if not self.user_id or not self.google_client:
            return
        
        try:
            from ...database import get_db_context
            from ...auth.token_refresh import refresh_token_if_needed
            
            with get_db_context() as db:
                from ...database.models import Session as DBSession
                session = db.query(DBSession).filter(
                    DBSession.user_id == self.user_id
                ).order_by(DBSession.created_at.desc()).first()
                
                if session:
                    was_refreshed, credentials = await refresh_token_if_needed(db, session)
                    if was_refreshed and credentials:
                        from ...core.email.google_client import GoogleGmailClient
                        self.google_client = GoogleGmailClient(self.config, credentials=credentials)
                        logger.info(f"Updated Gmail client with refreshed token for user {self.user_id}")
        except Exception as e:
            logger.debug(f"Token refresh check failed: {e}")


# ==================== Global Indexer Management ====================
# Singleton pattern for managing system-wide and per-user indexers

_background_indexer: Optional['IntelligentEmailIndexer'] = None
_user_background_indexers: Dict[int, 'IntelligentEmailIndexer'] = {}


async def get_background_indexer(
    config=None,
    rag_engine=None, 
    google_client=None,
    llm_client=None
) -> 'IntelligentEmailIndexer':
    """
    Get or create the global background email indexer (system-wide mode).
    
    This manages a singleton instance for system-wide email indexing.
    
    Args:
        config: Configuration object
        rag_engine: RAG engine for vector indexing
        google_client: Gmail client
        llm_client: LLM client for intent extraction
        
    Returns:
        IntelligentEmailIndexer instance
    """
    global _background_indexer
    
    if _background_indexer is None:
        from ...utils.config import load_config
        config = config or load_config("config/config.yaml")
        
        _background_indexer = IntelligentEmailIndexer(
            config=config,
            rag_engine=rag_engine,
            google_client=google_client,
            llm_client=llm_client
        )
    
    return _background_indexer


async def start_background_indexing(
    config=None,
    rag_engine=None,
    google_client=None,
    llm_client=None,
    initial_batch_size: int = 300
):
    """
    Start the global background email indexer (system-wide mode).
    
    Args:
        config: Configuration object
        rag_engine: RAG engine for vector indexing
        google_client: Gmail client
        llm_client: LLM client for intent extraction
        initial_batch_size: Number of emails to index immediately
    """
    indexer = await get_background_indexer(config, rag_engine, google_client, llm_client)
    await indexer.start(initial_batch_size=initial_batch_size)
    logger.info("Global background email indexing started")


async def start_user_background_indexing(
    user_id: int,
    config=None,
    rag_engine=None,
    google_client=None,
    llm_client=None,
    collection_name: Optional[str] = None,
    initial_batch_size: int = 300
):
    """
    Start background indexing for a specific user (per-user mode).
    
    Args:
        user_id: User ID to index emails for
        config: Configuration object
        rag_engine: RAG engine for vector indexing
        google_client: Gmail client with user's credentials (if None, will be created from database)
        llm_client: LLM client for intent extraction
        collection_name: Optional collection name (default: user_{user_id}_emails)
        initial_batch_size: Number of emails to index immediately
    """
    global _user_background_indexers
    
    if user_id in _user_background_indexers:
        logger.warning(f"Background indexer for user {user_id} is already running")
        return
    
    from ...utils.config import load_config
    from ...database import get_db_context
    from ...database.models import Session as DBSession
    from ...auth.token_refresh import get_valid_credentials
    from datetime import datetime
    
    config = config or load_config("config/config.yaml")
    
    # If google_client not provided, create it through service layer
    if google_client is None:
        logger.info(f"Creating Gmail service from database session for user {user_id}")
        try:
            from ...services.factory import ServiceFactory
            
            with get_db_context() as db:
                # Use ServiceFactory to create EmailService (handles credential loading)
                service_factory = ServiceFactory(config=config)
                email_service = service_factory.create_email_service(
                    user_id=user_id,
                    db_session=db
                )
                
                if not email_service or not email_service.gmail_client:
                    raise ValueError(f"Failed to create Gmail service for user {user_id}")
                
                # Access the underlying client from the service (needed for low-level API calls)
                google_client = email_service.gmail_client
                logger.info(f"[OK] Gmail client created via EmailService for user {user_id}")
                
        except Exception as e:
            logger.error(f"Failed to create Gmail service for user {user_id}: {e}", exc_info=True)
            raise ValueError(f"Cannot start indexing: Failed to create Gmail service: {e}")
    
    collection_name = collection_name or f"user_{user_id}_emails"
    
    indexer = IntelligentEmailIndexer(
        config=config,
        rag_engine=rag_engine,
        google_client=google_client,
        llm_client=llm_client,
        user_id=user_id,
        collection_name=collection_name
    )
    
    await indexer.start(initial_batch_size=initial_batch_size)
    _user_background_indexers[user_id] = indexer
    
    logger.info(f"Background email indexing started for user {user_id}")


async def stop_background_indexing():
    """
    Stop all background email indexers (global and per-user).
    
    Handles CancelledError gracefully during shutdown.
    """
    import asyncio
    global _background_indexer
    
    if _background_indexer:
        try:
            await _background_indexer.stop()
            _background_indexer = None
            logger.info("Global background email indexing stopped")
        except asyncio.CancelledError:
            # Expected during shutdown - task already cancelled
            logger.info("Global background indexing already cancelled")
            _background_indexer = None
        except Exception as e:
            logger.warning(f"Error stopping global background indexer: {e}")
    
    # Stop all user-specific indexers
    global _user_background_indexers
    for user_id, indexer in list(_user_background_indexers.items()):
        try:
            await indexer.stop()
            logger.info(f"Background email indexing stopped for user {user_id}")
        except asyncio.CancelledError:
            # Expected during shutdown - task already cancelled
            logger.info(f"Background indexing for user {user_id} already cancelled")
        except Exception as e:
            logger.warning(f"Error stopping indexer for user {user_id}: {e}")
    
    _user_background_indexers.clear()


def get_user_background_indexer(user_id: int) -> Optional['IntelligentEmailIndexer']:
    """
    Get the background indexer for a specific user.
    
    Args:
        user_id: User ID
        
    Returns:
        IntelligentEmailIndexer instance or None if not found
    """
    return _user_background_indexers.get(user_id)
