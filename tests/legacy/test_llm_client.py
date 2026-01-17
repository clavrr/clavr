"""
Tests for LLM client
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock

from src.ai.llm_client import LLMClient


class TestLLMClient:
    """Test LLM client functionality"""
    
    def test_init_openai(self, test_config):
        """Test OpenAI client initialization"""
        with patch('src.ai.llm_client.OpenAI'):
            client = LLMClient(test_config)
            assert client.provider == "openai"
            assert client.model == test_config.ai.model
    
    def test_init_anthropic(self, test_config):
        """Test Anthropic client initialization"""
        test_config.ai.provider = "anthropic"
        with patch('src.ai.llm_client.Anthropic'):
            client = LLMClient(test_config)
            assert client.provider == "anthropic"
    
    def test_init_invalid_provider(self, test_config):
        """Test invalid provider raises error"""
        test_config.ai.provider = "invalid"
        with pytest.raises(ValueError):
            LLMClient(test_config)
    
    def test_build_prompt(self, test_config):
        """Test prompt building"""
        with patch('src.ai.llm_client.OpenAI'):
            client = LLMClient(test_config)
            prompt = client._build_prompt(
                email_content="Test content",
                subject="Test subject",
                sender="test@example.com"
            )
            assert "Test content" in prompt
            assert "Test subject" in prompt
            assert "test@example.com" in prompt

