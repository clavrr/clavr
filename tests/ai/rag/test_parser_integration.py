"""
Integration Test: RAG Parser Integration

Tests the complete flow from document parsing to RAG indexing and search.
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from src.ai.rag import RAGEngine, DocumentProcessor, RAGIndexingService
from src.utils.config import Config, RAGConfig
from src.services.indexing.parsers.base import ParsedNode


@pytest.fixture
def mock_config():
    """Create mock configuration"""
    config = Mock(spec=Config)
    config.rag = RAGConfig(
        embedding_provider="sentence_transformer",
        vector_store_backend="chromadb",
        collection_name="test_docs",
        chunk_size=500,
        chunk_overlap=50,
        use_semantic_chunking=True
    )
    return config


@pytest.fixture
def mock_rag_engine(mock_config):
    """Create mock RAG engine"""
    with patch('src.ai.rag.rag_engine.create_embedding_provider'), \
         patch('src.ai.rag.rag_engine.create_vector_store'):
        engine = RAGEngine(mock_config)
        engine.index_document = Mock()
        engine.index_bulk_documents = Mock()
        engine.search = Mock(return_value=[])
        return engine


class TestDocumentProcessor:
    """Test DocumentProcessor integration"""
    
    @pytest.mark.asyncio
    async def test_process_document_flow(self, mock_rag_engine):
        """Test complete document processing flow"""
        # Create processor
        processor = DocumentProcessor(
            rag_engine=mock_rag_engine,
            chunk_size=500,
            chunk_overlap=50,
            use_semantic_chunking=True,
            preserve_structure=True
        )
        
        # Mock attachment parser
        mock_parsed_node = ParsedNode(
            node_id="test_doc_1",
            node_type="Document",
            properties={
                'full_text': "This is a test document. " * 100,
                'tables': [],
                'headings': [{'level': 1, 'text': 'Introduction'}],
                'sections': [
                    {
                        'heading': 'Introduction',
                        'level': 1,
                        'content': ['This is the introduction section.']
                    }
                ],
                'doc_type': 'pdf_document'
            },
            relationships=[]
        )
        
        with patch.object(
            processor.attachment_parser, 
            'parse', 
            new_callable=AsyncMock,
            return_value=mock_parsed_node
        ):
            # Process document
            result = await processor.process_document(
                file_bytes=b"fake pdf content",
                filename="test.pdf",
                doc_id="test_doc_1"
            )
        
        # Verify results
        assert result['doc_id'] == "test_doc_1"
        assert result['filename'] == "test.pdf"
        assert result['num_chunks'] > 0
        assert isinstance(result['chunk_ids'], list)
        
        # Verify RAG engine was called
        mock_rag_engine.index_bulk_documents.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_semantic_chunking(self, mock_rag_engine):
        """Test semantic chunking respects sentence boundaries"""
        processor = DocumentProcessor(
            rag_engine=mock_rag_engine,
            chunk_size=50,  # Small for testing
            chunk_overlap=10,
            use_semantic_chunking=True
        )
        
        # Create test content with clear sentences
        content_data = {
            'text': (
                "This is sentence one. This is sentence two. "
                "This is sentence three. This is sentence four. " * 10
            ),
            'tables': [],
            'headings': [],
            'sections': []
        }
        
        chunks = processor._create_semantic_chunks(content_data, "test.txt")
        
        # Verify chunks exist
        assert len(chunks) > 1
        
        # Verify each chunk ends with a sentence boundary
        for chunk in chunks:
            text = chunk['text'].strip()
            # Should end with period (sentence boundary)
            assert text.endswith('.')
    
    @pytest.mark.asyncio
    async def test_structure_preservation(self, mock_rag_engine):
        """Test structure-aware chunking preserves sections"""
        processor = DocumentProcessor(
            rag_engine=mock_rag_engine,
            preserve_structure=True
        )
        
        content_data = {
            'text': '',
            'tables': [],
            'headings': [],
            'sections': [
                {
                    'heading': 'Section 1',
                    'level': 1,
                    'content': ['Content for section 1']
                },
                {
                    'heading': 'Section 2',
                    'level': 1,
                    'content': ['Content for section 2']
                }
            ]
        }
        
        chunks = processor._chunk_by_sections(content_data, "test.pdf")
        
        # Should have chunks for each section
        assert len(chunks) >= 2
        
        # Verify section headings are preserved
        assert any('Section 1' in chunk['text'] for chunk in chunks)
        assert any('Section 2' in chunk['text'] for chunk in chunks)
    
    @pytest.mark.asyncio
    async def test_table_chunking(self, mock_rag_engine):
        """Test tables are kept intact in separate chunks"""
        processor = DocumentProcessor(
            rag_engine=mock_rag_engine
        )
        
        tables = [
            {
                'index': 0,
                'headers': ['Name', 'Age'],
                'rows': [['Alice', '30'], ['Bob', '25']],
                'num_rows': 2,
                'num_cols': 2
            }
        ]
        
        table_chunks = processor._create_table_chunks(tables, "test.pdf")
        
        # Should have one chunk per table
        assert len(table_chunks) == 1
        
        # Verify chunk type
        assert table_chunks[0]['chunk_type'] == 'table'
        
        # Verify markdown format
        assert '|' in table_chunks[0]['text']  # Markdown table format


class TestUnifiedParserRAGBridge:
    """Test UnifiedParserRAGBridge integration"""
    
    @pytest.mark.asyncio
    async def test_index_email(self, mock_rag_engine):
        """Test email indexing flow"""
        from src.ai.rag.parser_integration import UnifiedParserRAGBridge
        
        bridge = UnifiedParserRAGBridge(
            rag_engine=mock_rag_engine,
            llm_client=None
        )
        
        # Mock email parser
        mock_parsed_node = ParsedNode(
            node_id="email_1",
            node_type="Email",
            properties={
                'primary_intent': 'request',
                'urgency': 'normal',
                'action_items': ['Review document'],
                'key_entities': ['John Doe'],
                'categories': ['work']
            }
        )
        
        with patch.object(
            bridge.email_parser,
            'parse',
            new_callable=AsyncMock,
            return_value=mock_parsed_node
        ):
            # Mock RAG engine email indexing
            mock_rag_engine.index_email = Mock(return_value=['chunk_1', 'chunk_2'])
            
            email_data = {
                'subject': 'Test Email',
                'sender': 'test@example.com',
                'body': 'This is a test email.'
            }
            
            result = await bridge.index_email(email_data)
        
        # Verify result
        assert 'email_id' in result
        assert result['num_chunks'] == 2
        assert result['parsed_intent'] == 'request'
        assert len(result['action_items']) == 1
    
    @pytest.mark.asyncio
    async def test_document_type_detection(self, mock_rag_engine):
        """Test automatic document type detection"""
        from src.ai.rag.parser_integration import UnifiedParserRAGBridge
        
        bridge = UnifiedParserRAGBridge(
            rag_engine=mock_rag_engine
        )
        
        # Test receipt detection
        assert bridge._detect_document_type('receipt_2024.pdf', {}) == 'receipt'
        assert bridge._detect_document_type('invoice_123.pdf', {}) == 'receipt'
        
        # Test regular document
        assert bridge._detect_document_type('report.pdf', {}) == 'document'
        
        # Test with metadata
        metadata = {'doc_type': 'receipt'}
        assert bridge._detect_document_type('doc.pdf', metadata) == 'receipt'


class TestRAGIndexingService:
    """Test RAGIndexingService"""
    
    @pytest.mark.asyncio
    async def test_service_initialization(self, mock_rag_engine):
        """Test service initializes correctly"""
        from src.ai.rag.parser_integration import RAGIndexingService
        
        service = RAGIndexingService(
            rag_engine=mock_rag_engine,
            llm_client=None
        )
        
        assert service.bridge is not None
        assert service.bridge.rag_engine == mock_rag_engine
    
    @pytest.mark.asyncio
    async def test_get_stats(self, mock_rag_engine):
        """Test statistics retrieval"""
        from src.ai.rag.parser_integration import RAGIndexingService
        
        service = RAGIndexingService(rag_engine=mock_rag_engine)
        
        # Mock RAG engine stats
        mock_rag_engine.get_stats = Mock(return_value={
            'total_documents': 100,
            'embedding_provider': 'test'
        })
        
        stats = service.get_stats()
        
        assert 'emails_indexed' in stats
        assert 'documents_indexed' in stats
        assert 'total_chunks_created' in stats
        assert 'rag_stats' in stats


class TestEndToEndIntegration:
    """End-to-end integration tests"""
    
    @pytest.mark.asyncio
    async def test_full_document_pipeline(self, mock_rag_engine):
        """Test complete pipeline: parse → chunk → index → search"""
        from src.ai.rag.parser_integration import RAGIndexingService
        
        service = RAGIndexingService(rag_engine=mock_rag_engine)
        
        # Mock the full flow
        mock_parsed_node = ParsedNode(
            node_id="doc_1",
            node_type="Document",
            properties={
                'full_text': "Test document content. " * 50,
                'tables': [],
                'headings': [],
                'sections': [],
                'doc_type': 'pdf_document'
            }
        )
        
        with patch.object(
            service.bridge.attachment_parser,
            'parse',
            new_callable=AsyncMock,
            return_value=mock_parsed_node
        ):
            # Index document
            result = await service.bridge.index_document(
                file_bytes=b"fake content",
                filename="test.pdf"
            )
        
        # Verify indexing
        assert result['num_chunks'] > 0
        mock_rag_engine.index_bulk_documents.assert_called()
        
        # Mock search
        mock_rag_engine.search.return_value = [
            {
                'content': 'Test document content.',
                'confidence': 0.95,
                'metadata': {'doc_type': 'pdf_document'}
            }
        ]
        
        # Search indexed content
        search_results = mock_rag_engine.search("test query", k=5)
        
        assert len(search_results) > 0
        assert search_results[0]['confidence'] > 0.9


def test_chunker_import():
    """Test that chunkers are properly imported"""
    from src.ai.rag import TextChunker, EmailChunker
    
    text_chunker = TextChunker(chunk_size=500, overlap=50)
    assert text_chunker.chunk_size == 500
    
    email_chunker = EmailChunker(max_chunk_words=300)
    assert email_chunker.max_chunk_words == 300


def test_processor_import():
    """Test that processors are properly exported"""
    from src.ai.rag import DocumentProcessor, RAGIndexingService
    
    # Verify classes are accessible
    assert DocumentProcessor is not None
    assert RAGIndexingService is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
