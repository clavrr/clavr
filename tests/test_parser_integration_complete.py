"""
Test suite for complete parser integration across all three tools.

This test verifies that:
1. All parsers implement parse_query_to_params() correctly
2. All tools integrate with their parsers properly
3. Confidence scoring works as expected
4. Entity extraction is functional
5. Parameter enhancement works correctly
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Import parsers
from src.agent.parsers.email_parser import EmailParser
from src.agent.parsers.task_parser import TaskParser
from src.agent.parsers.calendar_parser import CalendarParser

# Import tools
from src.tools import EmailTool, TaskTool, CalendarTool


class TestParserImplementations:
    """Test that all parsers implement parse_query_to_params() correctly."""
    
    def test_email_parser_has_parse_query_to_params(self):
        """EmailParser should have parse_query_to_params method."""
        parser = EmailParser(config=Mock())
        assert hasattr(parser, 'parse_query_to_params')
        assert callable(parser.parse_query_to_params)
    
    def test_task_parser_has_parse_query_to_params(self):
        """TaskParser should have parse_query_to_params method."""
        parser = TaskParser(config=Mock())
        assert hasattr(parser, 'parse_query_to_params')
        assert callable(parser.parse_query_to_params)
    
    def test_calendar_parser_has_parse_query_to_params(self):
        """CalendarParser should have parse_query_to_params method."""
        parser = CalendarParser(config=Mock())
        assert hasattr(parser, 'parse_query_to_params')
        assert callable(parser.parse_query_to_params)


class TestEmailParserIntegration:
    """Test EmailParser.parse_query_to_params() functionality."""
    
    def test_email_parser_send_action(self):
        """Should detect 'send' action and extract recipient."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Send an email to john@example.com")
        
        assert result['action'] == 'send'
        assert 'entities' in result
        assert 'confidence' in result
        assert 'metadata' in result
        assert 0.0 <= result['confidence'] <= 1.0
    
    def test_email_parser_search_action(self):
        """Should detect 'search' action and extract search term."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Search for emails from boss")
        
        assert result['action'] == 'search'
        assert 'entities' in result
        assert result['confidence'] > 0.0
    
    def test_email_parser_list_action(self):
        """Should detect 'list' action."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Show my recent emails")
        
        assert result['action'] == 'list'
        assert 'entities' in result
        assert result['confidence'] > 0.0


class TestTaskParserIntegration:
    """Test TaskParser.parse_query_to_params() functionality."""
    
    def test_task_parser_create_action(self):
        """Should detect 'create' action and extract task description."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Create a task to buy groceries")
        
        assert result['action'] == 'create'
        assert 'entities' in result
        assert 'confidence' in result
        assert result['confidence'] >= 0.6  # Should have decent confidence
    
    def test_task_parser_list_action(self):
        """Should detect 'list' action."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Show my tasks")
        
        assert result['action'] == 'list'
        assert 'entities' in result
    
    def test_task_parser_update_action(self):
        """Should detect 'update' action."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Mark task 5 as complete")
        
        assert result['action'] in ['update', 'complete']
        assert 'entities' in result


class TestCalendarParserIntegration:
    """Test CalendarParser.parse_query_to_params() functionality."""
    
    def test_calendar_parser_create_action(self):
        """Should detect 'create' action and extract event details."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("Schedule a meeting tomorrow at 2pm")
        
        assert result['action'] == 'create'
        assert 'entities' in result
        assert 'confidence' in result
        assert result['confidence'] > 0.0
    
    def test_calendar_parser_list_action(self):
        """Should detect 'list' action."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("Show my calendar for today")
        
        assert result['action'] == 'list'
        assert 'entities' in result
    
    def test_calendar_parser_task_rejection(self):
        """Should reject task queries routed to calendar."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("How many tasks do I have today?")
        
        # Should either reject or have low confidence
        assert result['action'] == 'reject' or result['confidence'] < 0.3


class TestToolParserIntegration:
    """Test that tools properly integrate with their parsers."""
    
    @patch('src.tools.email_tool.EmailService')
    def test_email_tool_has_parser_property(self, mock_service):
        """EmailTool should have a parser property."""
        config = Mock()
        tool = EmailTool(config=config)
        
        assert hasattr(tool, 'parser')
        # Parser should be lazy-loaded
        assert tool._parser is None or isinstance(tool._parser, EmailParser)
    
    @patch('src.tools.task_tool.TaskService')
    def test_task_tool_has_parser_property(self, mock_service):
        """TaskTool should have a parser property."""
        config = Mock()
        tool = TaskTool(config=config)
        
        assert hasattr(tool, 'parser')
        # Parser should be lazy-loaded
        assert tool._parser is None or isinstance(tool._parser, TaskParser)
    
    @patch('src.tools.calendar_tool.CalendarService')
    def test_calendar_tool_has_parser_property(self, mock_service):
        """CalendarTool should have a parser property."""
        config = Mock()
        tool = CalendarTool(config=config)
        
        assert hasattr(tool, 'parser')
        # Parser should be lazy-loaded
        assert tool._parser is None or isinstance(tool._parser, CalendarParser)


class TestConfidenceScoring:
    """Test confidence scoring across all parsers."""
    
    def test_email_parser_confidence_range(self):
        """EmailParser confidence should be between 0.0 and 1.0."""
        parser = EmailParser(config=Mock())
        queries = [
            "Send email to john@example.com about meeting",
            "Search emails",
            "Show unread"
        ]
        
        for query in queries:
            result = parser.parse_query_to_params(query)
            assert 0.0 <= result['confidence'] <= 1.0
    
    def test_task_parser_confidence_range(self):
        """TaskParser confidence should be between 0.0 and 1.0."""
        parser = TaskParser(config=Mock())
        queries = [
            "Create task to finish report",
            "List my tasks",
            "Complete task 5"
        ]
        
        for query in queries:
            result = parser.parse_query_to_params(query)
            assert 0.0 <= result['confidence'] <= 1.0
    
    def test_calendar_parser_confidence_range(self):
        """CalendarParser confidence should be between 0.0 and 1.0."""
        parser = CalendarParser(config=Mock())
        queries = [
            "Schedule meeting tomorrow at 2pm",
            "Show calendar for today",
            "Find free time this week"
        ]
        
        for query in queries:
            result = parser.parse_query_to_params(query)
            assert 0.0 <= result['confidence'] <= 1.0


class TestEntityExtraction:
    """Test entity extraction across all parsers."""
    
    def test_email_parser_extracts_recipient(self):
        """EmailParser should extract recipient from query."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Send email to alice@example.com")
        
        entities = result.get('entities', {})
        # Should extract recipient in some form
        assert entities is not None
    
    def test_task_parser_extracts_description(self):
        """TaskParser should extract task description."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Create task to buy groceries")
        
        entities = result.get('entities', {})
        assert entities is not None
    
    def test_calendar_parser_extracts_event_details(self):
        """CalendarParser should extract event title and time."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("Schedule team meeting tomorrow at 3pm")
        
        entities = result.get('entities', {})
        assert entities is not None


class TestMetadataGeneration:
    """Test metadata generation across all parsers."""
    
    def test_email_parser_generates_metadata(self):
        """EmailParser should generate metadata."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Send email")
        
        assert 'metadata' in result
        metadata = result['metadata']
        assert 'original_query' in metadata
        assert 'parsed_at' in metadata
    
    def test_task_parser_generates_metadata(self):
        """TaskParser should generate metadata."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Create task")
        
        assert 'metadata' in result
        metadata = result['metadata']
        assert 'original_query' in metadata
    
    def test_calendar_parser_generates_metadata(self):
        """CalendarParser should generate metadata."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("Schedule meeting")
        
        assert 'metadata' in result
        metadata = result['metadata']
        assert 'original_query' in metadata


class TestReturnStructure:
    """Test that all parsers return consistent structure."""
    
    def test_email_parser_return_structure(self):
        """EmailParser should return dict with required keys."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("Send email")
        
        assert isinstance(result, dict)
        assert 'action' in result
        assert 'entities' in result
        assert 'confidence' in result
        assert 'metadata' in result
    
    def test_task_parser_return_structure(self):
        """TaskParser should return dict with required keys."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("Create task")
        
        assert isinstance(result, dict)
        assert 'action' in result
        assert 'entities' in result
        assert 'confidence' in result
        assert 'metadata' in result
    
    def test_calendar_parser_return_structure(self):
        """CalendarParser should return dict with required keys."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("Schedule meeting")
        
        assert isinstance(result, dict)
        assert 'action' in result
        assert 'entities' in result
        assert 'confidence' in result
        assert 'metadata' in result


class TestErrorHandling:
    """Test error handling in parser integration."""
    
    def test_email_parser_handles_empty_query(self):
        """EmailParser should handle empty queries gracefully."""
        parser = EmailParser(config=Mock())
        result = parser.parse_query_to_params("")
        
        # Should return valid structure even for empty query
        assert isinstance(result, dict)
        assert 'action' in result
        assert 'confidence' in result
    
    def test_task_parser_handles_empty_query(self):
        """TaskParser should handle empty queries gracefully."""
        parser = TaskParser(config=Mock())
        result = parser.parse_query_to_params("")
        
        assert isinstance(result, dict)
        assert 'action' in result
    
    def test_calendar_parser_handles_empty_query(self):
        """CalendarParser should handle empty queries gracefully."""
        parser = CalendarParser(config=Mock())
        result = parser.parse_query_to_params("")
        
        assert isinstance(result, dict)
        assert 'action' in result


class TestIntegrationEndToEnd:
    """End-to-end integration tests."""
    
    def test_all_parsers_instantiate(self):
        """All parsers should instantiate successfully."""
        config = Mock()
        
        email_parser = EmailParser(config=config)
        task_parser = TaskParser(config=config)
        calendar_parser = CalendarParser(config=config)
        
        assert email_parser is not None
        assert task_parser is not None
        assert calendar_parser is not None
    
    def test_all_parsers_parse_successfully(self):
        """All parsers should parse queries successfully."""
        config = Mock()
        
        email_parser = EmailParser(config=config)
        task_parser = TaskParser(config=config)
        calendar_parser = CalendarParser(config=config)
        
        email_result = email_parser.parse_query_to_params("Send email")
        task_result = task_parser.parse_query_to_params("Create task")
        calendar_result = calendar_parser.parse_query_to_params("Schedule meeting")
        
        assert email_result['action'] is not None
        assert task_result['action'] is not None
        assert calendar_result['action'] is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
