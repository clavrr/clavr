"""
Tests for message processor
"""
import pytest
from unittest.mock import Mock, AsyncMock

from src.email.message_processor import MessageProcessor
from src.ai.llm_client import LLMClient


class TestMessageProcessor:
    """Test message processor functionality"""
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client"""
        llm = Mock(spec=LLMClient)
        llm.generate_response = AsyncMock(return_value="Test response")
        return llm
    
    def test_init(self, test_config, mock_llm):
        """Test processor initialization"""
        processor = MessageProcessor(test_config, mock_llm)
        assert processor.config == test_config
        assert processor.llm == mock_llm
    
    @pytest.mark.asyncio
    async def test_process_message(self, test_config, mock_llm, sample_email):
        """Test processing a message"""
        processor = MessageProcessor(test_config, mock_llm)
        response = await processor.process_message(sample_email)
        
        assert response is not None
        assert isinstance(response, str)
        mock_llm.generate_response.assert_called_once()
    
    def test_extract_context(self, test_config, mock_llm, sample_email):
        """Test context extraction"""
        processor = MessageProcessor(test_config, mock_llm)
        context = processor._extract_context(sample_email)
        
        assert "sender" in context
        assert "subject" in context
        assert context["sender"] == sample_email.sender

