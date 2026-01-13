"""
Parser Integration Layer for RAG System

This module provides seamless integration between:
1. Agent parsers (email, task parsing)
2. Service parsers (document, receipt, attachment parsing with Docling)
3. RAG semantic chunking
4. Vector store indexing

It acts as the central orchestrator for all document ingestion into the RAG system.
"""
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
import hashlib
import asyncio


from typing import TYPE_CHECKING, List, Dict, Any, Optional, Union

from ....utils.logger import setup_logger

if TYPE_CHECKING:
    from ....services.indexing.parsers.base import ParsedNode
    from ....services.indexing.parsers import EmailParser, ReceiptParser, AttachmentParser

from ..core.rag_engine import RAGEngine

from ..chunking import RecursiveTextChunker
from ..chunking import EmailChunker
from .document_processor import DocumentProcessor

logger = setup_logger(__name__)


class UnifiedParserRAGBridge:
    """
    Unified bridge connecting all parsers to the RAG system.
    
    This class provides a single entry point for indexing various content types:
    - Emails (with EmailParser + EmailChunker)
    - Documents (PDF, DOCX, etc. with Docling + SemanticChunker)
    - Receipts (with specialized ReceiptParser)
    - General attachments (with AttachmentParser)
    
    Features:
    - Type-aware parsing and chunking
    - Metadata enrichment
    - Relationship preservation
    - Quality monitoring
    """
    
    def __init__(
        self,
        rag_engine: RAGEngine,
        llm_client: Optional[Any] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        """
        Initialize the unified parser bridge.
        
        Args:
            rag_engine: RAG engine for indexing
            llm_client: Optional LLM for enhanced parsing
            chunk_size: Default chunk size for documents
            chunk_overlap: Default chunk overlap
        """
        self.rag_engine = rag_engine
        self.llm_client = llm_client
        
        # Local imports to avoid circular dependency
        from ....services.indexing.parsers import EmailParser, ReceiptParser, AttachmentParser
        
        # Initialize specialized parsers
        self.email_parser = EmailParser(llm_client=llm_client)

        self.receipt_parser = ReceiptParser(llm_client=llm_client)
        self.attachment_parser = AttachmentParser(llm_client=llm_client)
        
        # Initialize specialized chunkers
        self.email_chunker = EmailChunker(chunk_size=300)
        
        # Initialize advanced recursive text chunker
        self.text_chunker = RecursiveTextChunker(
            chunk_size=int(chunk_size * 0.75),  # Convert words to tokens
            child_chunk_size=int(chunk_size * 0.75 // 2),  # Half of parent
            overlap_tokens=int(chunk_overlap * 0.75),  # Convert words to tokens
            use_parent_child=True  # Enable semantic mode
        )
        
        # Initialize document processor for complex documents
        self.document_processor = DocumentProcessor(
            rag_engine=rag_engine,
            llm_client=llm_client,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            use_semantic_chunking=True,
            preserve_structure=True
        )
        
        # Track indexing metrics
        self.metrics = {
            'emails_indexed': 0,
            'documents_indexed': 0,
            'receipts_indexed': 0,
            'total_chunks_created': 0,
            'parsing_errors': 0
        }
        
        logger.info("UnifiedParserRAGBridge initialized with all parsers and chunkers")
    
    async def index_email(
        self,
        email_data: Dict[str, Any],
        email_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Index an email with intelligent parsing and chunking.
        
        Args:
            email_data: Email data dict with subject, sender, body, etc.
            email_id: Optional email ID (auto-generated if not provided)
            
        Returns:
            Indexing result with chunk IDs and metadata
        """
        try:
            # Generate email_id if not provided
            if not email_id:
                email_str = f"{email_data.get('subject', '')}{email_data.get('date', '')}"
                email_id = f"email_{hashlib.md5(email_str.encode()).hexdigest()[:12]}"
            
            logger.debug(f"Indexing email: {email_id}")
            
            # Step 1: Parse email to extract structure and intent
            parsed_node = await self.email_parser.parse(email_data)
            
            # Step 2: Create email-aware chunks
            chunk_ids = self.rag_engine.index_email(email_id, email_data)
            
            # Step 3: Extract and store metadata
            metadata = self._extract_email_metadata(parsed_node, email_data)
            
            self.metrics['emails_indexed'] += 1
            self.metrics['total_chunks_created'] += len(chunk_ids)
            
            logger.info(f"Email indexed: {email_id} → {len(chunk_ids)} chunks")
            
            return {
                'email_id': email_id,
                'chunk_ids': chunk_ids,
                'num_chunks': len(chunk_ids),
                'metadata': metadata,
                'parsed_intent': parsed_node.properties.get('primary_intent'),
                'action_items': parsed_node.properties.get('action_items', [])
            }
            
        except Exception as e:
            logger.error(f"Failed to index email: {e}", exc_info=True)
            self.metrics['parsing_errors'] += 1
            raise
    
    async def index_document(
        self,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        doc_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        document_type: str = 'auto'
    ) -> Dict[str, Any]:
        """
        Index a document with Docling parsing and semantic chunking.
        
        Args:
            file_path: Path to document file
            file_bytes: Raw file bytes (alternative to file_path)
            filename: Original filename
            doc_id: Document ID (auto-generated if not provided)
            metadata: Additional metadata
            document_type: Document type hint ('auto', 'pdf', 'receipt', etc.)
            
        Returns:
            Indexing result with chunk IDs and statistics
        """
        try:
            # Detect document type if needed
            if document_type == 'auto':
                document_type = self._detect_document_type(filename, metadata)
            
            # Route to specialized parser for receipts
            if document_type == 'receipt':
                return await self._index_receipt(
                    file_path=file_path,
                    file_bytes=file_bytes,
                    filename=filename,
                    doc_id=doc_id,
                    metadata=metadata
                )
            
            # Use document processor for general documents
            result = await self.document_processor.process_document(
                file_path=file_path,
                file_bytes=file_bytes,
                filename=filename,
                doc_id=doc_id,
                metadata=metadata
            )
            
            self.metrics['documents_indexed'] += 1
            self.metrics['total_chunks_created'] += result['num_chunks']
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to index document {filename}: {e}", exc_info=True)
            self.metrics['parsing_errors'] += 1
            raise
    
    async def index_documents_batch(
        self,
        documents: List[Dict[str, Any]],
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Index multiple documents in batch with parallel processing.
        
        Args:
            documents: List of document specifications
            max_concurrent: Maximum concurrent processing
            
        Returns:
            List of indexing results
        """
        logger.info(f"Batch indexing {len(documents)} documents...")
        
        results = await self.document_processor.process_documents_batch(
            documents=documents,
            max_concurrent=max_concurrent
        )
        
        # Update metrics
        successful = sum(1 for r in results if 'error' not in r)
        self.metrics['documents_indexed'] += successful
        self.metrics['total_chunks_created'] += sum(
            r.get('num_chunks', 0) for r in results
        )
        
        return results
    
    async def _index_receipt(
        self,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        doc_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Index a receipt with specialized parsing."""
        # Read file if needed
        if file_path and not file_bytes:
            loop = asyncio.get_running_loop()
            file_bytes = await loop.run_in_executor(None, Path(file_path).read_bytes)
            filename = filename or Path(file_path).name
        
        # Generate doc_id
        if not doc_id:
            doc_id = f"receipt_{hashlib.md5(file_bytes).hexdigest()[:12]}"
        
        logger.info(f"Indexing receipt: {filename}")
        
        # Parse receipt
        parsed_node = await self.receipt_parser.parse(
            attachment_data=file_bytes,
            filename=filename
        )
        
        # Extract receipt-specific content
        receipt_text = self._format_receipt_for_indexing(parsed_node)
        
        # Index with metadata
        receipt_metadata = {
            **(metadata or {}),
            'doc_type': 'receipt',
            'vendor': parsed_node.properties.get('vendor'),
            'amount': parsed_node.properties.get('total_amount'),
            'date': parsed_node.properties.get('date'),
            'category': parsed_node.properties.get('category'),
            'arango_node_id': doc_id,  # ← THE BRIDGE: Links receipt to graph node (matches architecture)
            'node_id': doc_id  # Also keep for backward compatibility
        }
        
        self.rag_engine.index_document(doc_id, receipt_text, receipt_metadata)
        
        self.metrics['receipts_indexed'] += 1
        self.metrics['total_chunks_created'] += 1
        
        return {
            'doc_id': doc_id,
            'filename': filename,
            'chunk_ids': [doc_id],
            'num_chunks': 1,
            'receipt_data': {
                'vendor': parsed_node.properties.get('vendor'),
                'amount': parsed_node.properties.get('total_amount'),
                'date': parsed_node.properties.get('date')
            }
        }
    
    def _detect_document_type(
        self,
        filename: Optional[str],
        metadata: Optional[Dict[str, Any]]
    ) -> str:
        """Detect document type from filename and metadata."""
        if not filename:
            return 'document'
        
        filename_lower = filename.lower()
        
        # Check for receipt indicators
        receipt_keywords = ['receipt', 'invoice', 'bill']
        if any(kw in filename_lower for kw in receipt_keywords):
            return 'receipt'
        
        # Check metadata
        if metadata and metadata.get('doc_type') == 'receipt':
            return 'receipt'
        
        return 'document'
    
    def _extract_email_metadata(
        self,
        parsed_node: 'ParsedNode',
        email_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract enriched metadata from parsed email."""
        return {
            'subject': email_data.get('subject', ''),
            'sender': email_data.get('sender', ''),
            'date': email_data.get('date', ''),
            'intent': parsed_node.properties.get('primary_intent'),
            'urgency': parsed_node.properties.get('urgency', 'normal'),
            'sentiment': parsed_node.properties.get('sentiment'),
            'has_action_items': len(parsed_node.properties.get('action_items', [])) > 0,
            'num_action_items': len(parsed_node.properties.get('action_items', [])),
            'categories': parsed_node.properties.get('categories', []),
            'key_entities': parsed_node.properties.get('key_entities', [])
        }
    
    def _format_receipt_for_indexing(self, parsed_node: 'ParsedNode') -> str:
        """Format receipt data as searchable text."""
        props = parsed_node.properties
        
        lines = [
            f"Receipt from {props.get('vendor', 'Unknown')}",
            f"Date: {props.get('date', 'Unknown')}",
            f"Total Amount: {props.get('total_amount', 'Unknown')}",
            f"Category: {props.get('category', 'Uncategorized')}",
        ]
        
        # Add items
        items = props.get('items', [])
        if items:
            lines.append("\nItems:")
            for item in items:
                lines.append(f"- {item.get('description', 'Unknown')} (${item.get('price', 'N/A')})")
        
        return '\n'.join(lines)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get indexing metrics and statistics."""
        return {
            **self.metrics,
            'rag_stats': self.rag_engine.get_stats(),
            'document_processor_stats': self.document_processor.get_stats()
        }
    
    def reset_metrics(self):
        """Reset indexing metrics."""
        self.metrics = {
            'emails_indexed': 0,
            'documents_indexed': 0,
            'receipts_indexed': 0,
            'total_chunks_created': 0,
            'parsing_errors': 0
        }
        logger.info("Indexing metrics reset")


class RAGIndexingService:
    """
    High-level service for RAG indexing operations.
    
    This is the recommended interface for applications that need to index
    various content types into the RAG system.
    """
    
    def __init__(self, rag_engine: RAGEngine, llm_client: Optional[Any] = None):
        """Initialize RAG indexing service."""
        self.bridge = UnifiedParserRAGBridge(
            rag_engine=rag_engine,
            llm_client=llm_client
        )
        logger.info("RAGIndexingService initialized")
    
    async def index_email(self, email_data: Dict[str, Any], email_id: Optional[str] = None):
        """Index an email."""
        return await self.bridge.index_email(email_data, email_id)
    
    async def index_pdf(self, file_path: str, metadata: Optional[Dict[str, Any]] = None):
        """Index a PDF document."""
        return await self.bridge.index_document(
            file_path=file_path,
            metadata=metadata,
            document_type='pdf'
        )
    
    async def index_office_document(self, file_path: str, metadata: Optional[Dict[str, Any]] = None):
        """Index an Office document (DOCX, PPTX, XLSX)."""
        return await self.bridge.index_document(
            file_path=file_path,
            metadata=metadata,
            document_type='office'
        )
    
    async def index_receipt(self, file_path: str, metadata: Optional[Dict[str, Any]] = None):
        """Index a receipt."""
        return await self.bridge.index_document(
            file_path=file_path,
            metadata=metadata,
            document_type='receipt'
        )
    
    async def index_directory(
        self,
        directory_path: str,
        recursive: bool = True,
        file_extensions: Optional[List[str]] = None,
        max_concurrent: int = 5
    ) -> Dict[str, Any]:
        """
        Index all documents in a directory.
        
        Args:
            directory_path: Path to directory
            recursive: Recursively process subdirectories
            file_extensions: File extensions to process (None = all)
            max_concurrent: Maximum concurrent processing
            
        Returns:
            Summary with statistics
        """
        from pathlib import Path
        
        directory = Path(directory_path)
        if not directory.exists():
            raise ValueError(f"Directory not found: {directory_path}")
        
        # Find all files
        if recursive:
            pattern = '**/*'
        else:
            pattern = '*'
        
        files = []
        for file_path in directory.glob(pattern):
            if not file_path.is_file():
                continue
            
            # Filter by extension if specified
            if file_extensions and file_path.suffix.lower() not in file_extensions:
                continue
            
            files.append({
                'file_path': str(file_path),
                'filename': file_path.name
            })
        
        logger.info(f"Found {len(files)} files to index in {directory_path}")
        
        # Batch process
        results = await self.bridge.index_documents_batch(
            documents=files,
            max_concurrent=max_concurrent
        )
        
        # Generate summary
        successful = sum(1 for r in results if 'error' not in r)
        total_chunks = sum(r.get('num_chunks', 0) for r in results)
        
        return {
            'directory': directory_path,
            'total_files': len(files),
            'successful': successful,
            'failed': len(files) - successful,
            'total_chunks_created': total_chunks,
            'results': results
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        return self.bridge.get_metrics()
