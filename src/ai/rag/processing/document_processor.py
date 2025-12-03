"""
Enhanced Document Processing Pipeline for RAG System

This module integrates:
1. Docling-based document parsing (PDFs, Office docs, etc.)
2. Gold-level semantic chunking
3. RAG engine indexing

The pipeline ensures high-quality document processing for optimal retrieval.
"""
import asyncio
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from datetime import datetime

from ....utils.logger import setup_logger
from ....services.indexing.parsers.attachment_parser import AttachmentParser
from ....services.indexing.parsers.base import ParsedNode
from ..chunking import RecursiveTextChunker
from ..core.rag_engine import RAGEngine

logger = setup_logger(__name__)


class DocumentProcessor:
    """
    High-level document processing orchestrator for RAG systems.
    
    This class provides a unified pipeline for:
    1. Parsing documents using Docling (PDFs, DOCX, PPTX, etc.)
    2. Applying semantic-aware chunking
    3. Indexing chunks into the RAG engine
    
    Features:
    - Multi-format document support via Docling
    - Semantic chunking with sentence/paragraph awareness
    - Structure-aware chunking (preserves headings, tables)
    - Metadata enrichment for better retrieval
    - Batch processing for efficiency
    """
    
    def __init__(
        self,
        rag_engine: RAGEngine,
        llm_client: Optional[Any] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        use_semantic_chunking: bool = True,
        preserve_structure: bool = True
    ):
        """
        Initialize document processor.
        
        Args:
            rag_engine: RAG engine for indexing
            llm_client: Optional LLM for enhanced extraction
            chunk_size: Target chunk size in words
            chunk_overlap: Overlap between chunks in words
            use_semantic_chunking: Use semantic-aware chunking
            preserve_structure: Preserve document structure (headings, tables)
        """
        self.rag_engine = rag_engine
        self.attachment_parser = AttachmentParser(llm_client=llm_client)
        
        # Initialize advanced recursive text chunker
        self.chunker = RecursiveTextChunker(
            chunk_size=int(chunk_size * 0.75),  # Convert words to tokens
            child_chunk_size=int(chunk_size * 0.75 // 2),  # Half of parent
            overlap_tokens=int(chunk_overlap * 0.75),  # Convert words to tokens
            use_parent_child=use_semantic_chunking  # Enable for semantic mode
        )
        self.preserve_structure = preserve_structure
        
        logger.info(
            f"DocumentProcessor initialized: "
            f"chunk_size={chunk_size}, "
            f"overlap={chunk_overlap}, "
            f"semantic={use_semantic_chunking}, "
            f"preserve_structure={preserve_structure}"
        )
    
    async def process_document(
        self,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        doc_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a single document through the complete pipeline.
        
        Args:
            file_path: Path to document file (or use file_bytes)
            file_bytes: Raw file bytes (or use file_path)
            filename: Original filename
            doc_id: Document ID (auto-generated if not provided)
            metadata: Additional metadata to attach
            
        Returns:
            Processing result with chunk IDs and statistics
        """
        # Read file if path provided
        if file_path and not file_bytes:
            file_bytes = Path(file_path).read_bytes()
            filename = filename or Path(file_path).name
        
        if not file_bytes or not filename:
            raise ValueError("Must provide either file_path or (file_bytes + filename)")
        
        # Generate doc_id if not provided
        if not doc_id:
            import hashlib
            doc_id = f"doc_{hashlib.md5(file_bytes).hexdigest()[:12]}"
        
        logger.info(f"Processing document: {filename} (id: {doc_id})")
        
        # Step 1: Parse document using Docling
        parsed_node = await self.attachment_parser.parse(
            attachment_data=file_bytes,
            filename=filename,
            email_id=None,
            metadata=metadata
        )
        
        # Step 2: Extract content and structure
        content_data = self._extract_content_from_node(parsed_node)
        
        # Step 3: Apply semantic chunking
        chunks = self._create_semantic_chunks(content_data, filename)
        
        # Step 4: Index chunks into RAG engine
        chunk_ids = await self._index_chunks(
            doc_id=doc_id,
            chunks=chunks,
            base_metadata=metadata or {}
        )
        
        logger.info(
            f"Document processed: {filename} → {len(chunk_ids)} chunks indexed"
        )
        
        return {
            'doc_id': doc_id,
            'filename': filename,
            'chunk_ids': chunk_ids,
            'num_chunks': len(chunk_ids),
            'total_chars': sum(len(c['text']) for c in chunks),
            'has_tables': content_data.get('has_tables', False),
            'num_tables': len(content_data.get('tables', [])),
            'num_headings': len(content_data.get('headings', []))
        }
    
    async def process_documents_batch(
        self,
        documents: List[Dict[str, Any]],
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Process multiple documents in parallel.
        
        Args:
            documents: List of document specs, each with:
                - file_path or file_bytes
                - filename
                - doc_id (optional)
                - metadata (optional)
            max_concurrent: Maximum concurrent processing
            
        Returns:
            List of processing results
        """
        logger.info(f"Batch processing {len(documents)} documents...")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(doc_spec):
            async with semaphore:
                try:
                    return await self.process_document(**doc_spec)
                except Exception as e:
                    logger.error(f"Failed to process {doc_spec.get('filename')}: {e}")
                    return {
                        'doc_id': doc_spec.get('doc_id'),
                        'filename': doc_spec.get('filename'),
                        'error': str(e),
                        'num_chunks': 0
                    }
        
        results = await asyncio.gather(*[
            process_with_semaphore(doc) for doc in documents
        ])
        
        successful = sum(1 for r in results if 'error' not in r)
        logger.info(f"Batch processing complete: {successful}/{len(documents)} succeeded")
        
        return results
    
    def _extract_content_from_node(self, parsed_node: ParsedNode) -> Dict[str, Any]:
        """
        Extract content and structure from parsed node.
        
        Args:
            parsed_node: Parsed document node from AttachmentParser
            
        Returns:
            Dictionary with text, tables, headings, sections
        """
        properties = parsed_node.properties
        
        # Extract main text
        text = properties.get('full_text', '')
        
        # Extract structured elements
        tables = properties.get('tables', [])
        headings = properties.get('headings', [])
        sections = properties.get('sections', [])
        
        return {
            'text': text,
            'tables': tables,
            'headings': headings,
            'sections': sections,
            'has_tables': len(tables) > 0,
            'doc_type': properties.get('doc_type', 'document')
        }
    
    def _create_semantic_chunks(
        self,
        content_data: Dict[str, Any],
        filename: str
    ) -> List[Dict[str, Any]]:
        """
        Create semantic chunks from document content.
        
        This method implements intelligent chunking:
        1. If preserve_structure=True, creates chunks based on document structure
        2. Otherwise, uses standard semantic chunking on full text
        3. Special handling for tables (kept intact when possible)
        
        Args:
            content_data: Extracted content with text, tables, headings
            filename: Original filename for context
            
        Returns:
            List of chunk dictionaries with text and metadata
        """
        chunks = []
        
        if self.preserve_structure and content_data.get('sections'):
            # Structure-aware chunking: chunk per section
            chunks = self._chunk_by_sections(content_data, filename)
        else:
            # Standard semantic chunking on full text
            chunks = self._chunk_full_text(content_data, filename)
        
        # Add table chunks separately (tables are kept intact)
        if content_data.get('tables'):
            table_chunks = self._create_table_chunks(content_data['tables'], filename)
            chunks.extend(table_chunks)
        
        logger.debug(
            f"Created {len(chunks)} chunks for {filename} "
            f"(structure_aware={self.preserve_structure})"
        )
        
        return chunks
    
    def _chunk_by_sections(
        self,
        content_data: Dict[str, Any],
        filename: str
    ) -> List[Dict[str, Any]]:
        """
        Create chunks based on document sections (structure-aware).
        
        Each section becomes one or more chunks, preserving the semantic
        structure of the document.
        """
        chunks = []
        sections = content_data.get('sections', [])
        
        for idx, section in enumerate(sections):
            heading = section.get('heading', '')
            section_content = '\n'.join(section.get('content', []))
            
            # Combine heading and content
            full_section_text = f"# {heading}\n\n{section_content}" if heading else section_content
            
            # Chunk the section if it's too long
            section_chunks = self.chunker.chunk(full_section_text)
            
            for chunk_idx, chunk_obj in enumerate(section_chunks):
                # Extract text from Chunk object
                chunk_text = chunk_obj.text if hasattr(chunk_obj, 'text') else str(chunk_obj)
                chunks.append({
                    'text': chunk_text,
                    'chunk_type': 'section',
                    'section_index': idx,
                    'section_heading': heading,
                    'chunk_index_in_section': chunk_idx,
                    'source_filename': filename
                })
        
        return chunks
    
    def _chunk_full_text(
        self,
        content_data: Dict[str, Any],
        filename: str
    ) -> List[Dict[str, Any]]:
        """
        Create chunks from full document text using semantic chunking.
        """
        text = content_data.get('text', '')
        
        if not text:
            return []
        
        # Apply semantic chunking
        chunk_objects = self.chunker.chunk(text)
        
        chunks = []
        for idx, chunk_obj in enumerate(chunk_objects):
            # Extract text from Chunk object
            chunk_text = chunk_obj.text if hasattr(chunk_obj, 'text') else str(chunk_obj)
            chunks.append({
                'text': chunk_text,
                'chunk_type': 'text',
                'chunk_index': idx,
                'source_filename': filename
            })
        
        return chunks
    
    def _create_table_chunks(
        self,
        tables: List[Dict[str, Any]],
        filename: str
    ) -> List[Dict[str, Any]]:
        """
        Create separate chunks for tables.
        
        Tables are kept intact (not split) to preserve their structure.
        """
        chunks = []
        
        for idx, table in enumerate(tables):
            # Convert table to markdown format for better readability
            table_text = self._table_to_markdown(table)
            
            chunks.append({
                'text': table_text,
                'chunk_type': 'table',
                'table_index': idx,
                'num_rows': table.get('num_rows', 0),
                'num_cols': table.get('num_cols', 0),
                'source_filename': filename
            })
        
        return chunks
    
    def _table_to_markdown(self, table: Dict[str, Any]) -> str:
        """Convert table data to markdown format."""
        headers = table.get('headers', [])
        rows = table.get('rows', [])
        
        if not headers and not rows:
            return "[Empty Table]"
        
        # Create markdown table
        md_lines = []
        
        # Header row
        if headers:
            md_lines.append('| ' + ' | '.join(str(h) for h in headers) + ' |')
            md_lines.append('|' + '---|' * len(headers))
        
        # Data rows
        for row in rows:
            md_lines.append('| ' + ' | '.join(str(cell) for cell in row) + ' |')
        
        return '\n'.join(md_lines)
    
    async def _index_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        base_metadata: Dict[str, Any]
    ) -> List[str]:
        """
        Index chunks into RAG engine.
        
        Args:
            doc_id: Base document ID
            chunks: List of chunk dictionaries
            base_metadata: Base metadata to attach to all chunks
            
        Returns:
            List of chunk IDs
        """
        chunk_ids = []
        documents = []
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{idx}"
            chunk_ids.append(chunk_id)
            
            # Merge chunk metadata with base metadata
            chunk_metadata = {
                **base_metadata,
                'parent_doc_id': doc_id,
                'chunk_index': idx,
                'total_chunks': len(chunks),
                'chunk_type': chunk.get('chunk_type', 'text'),
                'indexed_at': datetime.utcnow().isoformat()
            }
            
            # Add chunk-specific metadata
            if chunk.get('section_heading'):
                chunk_metadata['section_heading'] = chunk['section_heading']
            if chunk.get('table_index') is not None:
                chunk_metadata['table_index'] = chunk['table_index']
            
            documents.append({
                'id': chunk_id,
                'content': chunk['text'],
                'metadata': chunk_metadata
            })
        
        # Batch index into RAG engine
        self.rag_engine.index_bulk_documents(documents)
        
        return chunk_ids
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return {
            'chunker_config': {
                'chunk_size': self.chunker.chunk_size,
                'overlap': self.chunker.overlap,
                'semantic': self.chunker.use_semantic
            },
            'preserve_structure': self.preserve_structure,
            'rag_stats': self.rag_engine.get_stats()
        }
