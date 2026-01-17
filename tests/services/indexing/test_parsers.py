"""
Tests for new knowledge graph parsers with IBM Docling integration
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from pathlib import Path

from src.services.indexing.parsers import (
    EmailParser,
    ReceiptParser,
    AttachmentParser,
    ParsedNode,
    Relationship
)


@pytest.fixture
def mock_llm():
    """Mock LLM client for testing"""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content='{"summary": "test", "confidence": 0.8}'))
    return llm


class TestEmailParser:
    """Test EmailParser functionality"""
    
    @pytest.mark.asyncio
    async def test_basic_email_parsing(self, mock_llm):
        """Test basic email parsing without LLM"""
        parser = EmailParser(llm_client=None)
        
        email_data = {
            'id': 'msg_123',
            'subject': 'Team Meeting Tomorrow',
            'from': 'john@company.com',
            'to': ['team@company.com'],
            'body': 'Please send me the Q4 report before the meeting.',
            'date': '2024-01-15T10:00:00Z',
            'attachments': []
        }
        
        node = await parser.parse(email_data)
        
        # Verify node structure
        assert node.node_type == 'Email'
        assert node.properties['subject'] == 'Team Meeting Tomorrow'
        assert 'intents' in node.properties
        assert len(node.relationships) > 0
    
    @pytest.mark.asyncio
    async def test_email_with_llm_intent_extraction(self, mock_llm):
        """Test email parsing with LLM-based intent extraction"""
        # Mock LLM response with proper JSON
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"action_items": ["send Q4 report"], "intents": ["request_info"], "questions": [], "topics": ["meeting", "report"], "entities": {"people": ["John"], "dates": ["tomorrow"]}, "confidence": 0.9}'
        ))
        
        parser = EmailParser(llm_client=mock_llm)
        
        email_data = {
            'id': 'msg_124',
            'subject': 'Q4 Report Request',
            'from': 'boss@company.com',
            'to': ['john@company.com'],
            'body': 'John, please send me the Q4 report by tomorrow.',
            'date': '2024-01-15T10:00:00Z',
            'attachments': []
        }
        
        node = await parser.parse(email_data)
        
        # Verify LLM was called
        assert mock_llm.ainvoke.called
        
        # Verify extracted intents
        assert 'intents' in node.properties
        intents = node.properties['intents']
        assert 'action_items' in intents
        assert len(intents['action_items']) > 0


class TestReceiptParser:
    """Test ReceiptParser functionality"""
    
    @pytest.mark.asyncio
    async def test_pdf_receipt_parsing_without_docling(self):
        """Test receipt parsing with fallback (no Docling)"""
        parser = ReceiptParser(llm_client=None)
        
        # Create minimal PDF-like data
        pdf_data = b"%PDF-1.4\nChipotle\nTotal: $12.50\n01/15/2024"
        
        node = await parser.parse(pdf_data, "receipt.pdf")
        
        # Verify node structure
        assert node.node_type == 'Receipt'
        assert node.properties['filename'] == 'receipt.pdf'
        # With fallback, some fields may be empty
        assert 'total' in node.properties
    
    @pytest.mark.asyncio
    async def test_receipt_with_llm_extraction(self, mock_llm):
        """Test receipt with LLM-based extraction"""
        # Mock LLM response
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"merchant": "Chipotle", "total": 12.50, "date": "2024-01-15", "category": "food", "confidence": 0.9}'
        ))
        
        parser = ReceiptParser(llm_client=mock_llm)
        
        receipt_text = b"Chipotle Mexican Grill\nBurrito Bowl $9.50\nDrink $3.00\nTotal: $12.50\n01/15/2024"
        
        node = await parser.parse(receipt_text, "receipt.pdf")
        
        # Verify extraction
        assert node.node_type == 'Receipt'
        # LLM should have been called
        assert mock_llm.ainvoke.called


class TestAttachmentParser:
    """Test AttachmentParser functionality"""
    
    @pytest.mark.asyncio
    async def test_text_file_parsing(self):
        """Test parsing plain text files"""
        parser = AttachmentParser(llm_client=None)
        
        text_data = b"This is a test document.\nIt has multiple lines.\nWith some content."
        
        node = await parser.parse(
            attachment_data=text_data,
            filename="document.txt",
            email_id="Email_123"
        )
        
        # Verify node structure
        assert node.node_type == 'Document'
        assert node.properties['filename'] == 'document.txt'
        assert node.properties['doc_type'] == 'text'
        assert len(node.properties['full_text']) > 0
        
        # Verify relationship to email
        email_relationship = [r for r in node.relationships if r.rel_type == 'ATTACHED_TO']
        assert len(email_relationship) > 0
    
    @pytest.mark.asyncio
    async def test_pdf_document_parsing_without_docling(self):
        """Test PDF parsing with fallback"""
        parser = AttachmentParser(llm_client=None)
        
        # Minimal PDF-like data
        pdf_data = b"%PDF-1.4\nQ4 Financial Report\nRevenue: $1M\nExpenses: $500K"
        
        node = await parser.parse(
            attachment_data=pdf_data,
            filename="Q4_Report.pdf",
            email_id="Email_456"
        )
        
        # Verify node structure
        assert node.node_type == 'Document'
        assert node.properties['filename'] == 'Q4_Report.pdf'
        assert node.properties['doc_type'] == 'pdf_document'
    
    @pytest.mark.asyncio
    async def test_document_with_llm_summarization(self, mock_llm):
        """Test document parsing with LLM summarization"""
        # Mock LLM response
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"summary": "Q4 financial report showing revenue growth", "document_type": "report", "key_points": ["Revenue up 15%"], "entities": {"companies": ["Acme Corp"]}, "topics": ["finance"], "confidence": 0.85}'
        ))
        
        parser = AttachmentParser(llm_client=mock_llm)
        
        doc_data = b"Q4 Financial Report\n\nAcme Corp achieved 15% revenue growth in Q4."
        
        node = await parser.parse(
            attachment_data=doc_data,
            filename="report.txt",
            email_id="Email_789"
        )
        
        # Verify LLM was called
        assert mock_llm.ainvoke.called
        
        # Verify structured data exists
        assert 'summary' in node.properties
        assert 'entities' in node.properties


class TestParserIntegration:
    """Test parsers working together"""
    
    @pytest.mark.asyncio
    async def test_email_with_attachment(self, mock_llm):
        """Test parsing email with attachment"""
        email_parser = EmailParser(llm_client=None)
        attachment_parser = AttachmentParser(llm_client=None)
        
        # Parse email first
        email_data = {
            'id': 'msg_999',
            'subject': 'Report Attached',
            'from': 'sender@company.com',
            'to': ['recipient@company.com'],
            'body': 'Please see attached report.',
            'date': '2024-01-15T10:00:00Z',
            'attachments': [
                {'filename': 'report.txt', 'content_type': 'text/plain'}
            ]
        }
        
        email_node = await email_parser.parse(email_data)
        
        # Parse attachment
        attachment_data = b"Important report content."
        attachment_node = await attachment_parser.parse(
            attachment_data=attachment_data,
            filename="report.txt",
            email_id=email_node.node_id
        )
        
        # Verify relationship
        assert email_node.node_id in [r.from_node for r in attachment_node.relationships]


def test_parsed_node_creation():
    """Test ParsedNode creation"""
    node = ParsedNode(
        node_id="Test_123",
        node_type="TestNode",
        properties={"key": "value"},
        relationships=[],
        searchable_text="test content"
    )
    
    assert node.node_id == "Test_123"
    assert node.node_type == "TestNode"
    assert node.properties["key"] == "value"


def test_relationship_creation():
    """Test Relationship creation"""
    rel = Relationship(
        from_node="Node_A",
        to_node="Node_B",
        rel_type="CONNECTS_TO",
        properties={"weight": 0.8}
    )
    
    assert rel.from_node == "Node_A"
    assert rel.to_node == "Node_B"
    assert rel.rel_type == "CONNECTS_TO"
    assert rel.properties["weight"] == 0.8


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
