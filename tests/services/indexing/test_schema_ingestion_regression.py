
import pytest
from unittest.mock import MagicMock
from datetime import datetime
import sys

# Ensure we can import from src
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from src.services.indexing.crawlers.notion import NotionCrawler
from src.services.indexing.crawlers.asana import AsanaCrawler
from src.services.indexing.graph.schema import NodeType

# Mock dependencies that might cause import errors or side effects
sys.modules['src.ai.rag'] = MagicMock()
sys.modules['src.services.rag_service'] = MagicMock()
sys.modules['src.ai.llm_factory'] = MagicMock()
sys.modules['langchain_google_genai'] = MagicMock()


class TestNotionSchemaIngestion:
    
    @pytest.fixture
    def notion_crawler(self):
        config = MagicMock()
        crawler = NotionCrawler(config=config, user_id=1, notion_client=MagicMock())
        return crawler

    def test_extract_notion_schema_properties_simple(self, notion_crawler):
        """Test extraction of simple Notion properties."""
        properties = {
            "Status": {"type": "status", "status": {"name": "In Progress"}},
            "Priority": {"type": "select", "select": {"name": "High"}},
            "Cost": {"type": "number", "number": 100},
            "Is Done": {"type": "checkbox", "checkbox": True},
            "Link": {"type": "url", "url": "http://example.com"},
            "Contact": {"type": "email", "email": "test@example.com"},
            "Phone": {"type": "phone_number", "phone_number": "123-456-7890"}
        }
        
        schema_props = notion_crawler._extract_schema_properties(properties)
        
        assert schema_props["Status"] == "In Progress"
        assert schema_props["Priority"] == "High"
        assert schema_props["Cost"] == 100
        assert schema_props["Is Done"] is True
        assert schema_props["Link"] == "http://example.com"
        assert schema_props["Contact"] == "test@example.com"
        assert schema_props["Phone"] == "123-456-7890"

    def test_extract_notion_schema_properties_complex(self, notion_crawler):
        """Test extraction of complex Notion properties (Multi-select, Date, Files, People)."""
        properties = {
            "Tags": {
                "type": "multi_select", 
                "multi_select": [{"name": "Tag1"}, {"name": "Tag2"}]
            },
            "Timeline": {
                "type": "date", 
                "date": {"start": "2023-01-01", "end": "2023-01-31"}
            },
            "Files": {
                "type": "files",
                "files": [{"name": "report.pdf"}, {"name": "image.png"}]
            },
            "Assignees": {
                "type": "people",
                "people": [{"name": "Alice"}, {"name": "Bob"}]
            },
            "Description": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "This is a "}, {"plain_text": "description"}]
            }
        }
        
        schema_props = notion_crawler._extract_schema_properties(properties)
        
        assert schema_props["Tags"] == ["Tag1", "Tag2"]
        assert schema_props["Timeline"] == "2023-01-01 to 2023-01-31"
        assert schema_props["Files"] == ["report.pdf", "image.png"]
        assert schema_props["Assignees"] == ["Alice", "Bob"]
        assert schema_props["Description"] == "This is a description"

    def test_extract_notion_schema_properties_empty_or_missing(self, notion_crawler):
        """Test that empty or missing values are skipped."""
        properties = {
            "Empty Select": {"type": "select", "select": None},
            "Empty Multi": {"type": "multi_select", "multi_select": []},
            "Empty Text": {"type": "rich_text", "rich_text": []},
            "Null Number": {"type": "number", "number": None}
        }
        
        schema_props = notion_crawler._extract_schema_properties(properties)
        
        assert schema_props == {}


class TestAsanaSchemaIngestion:
    
    @pytest.fixture
    def asana_crawler(self):
        config = MagicMock()
        # Mock ServiceConstants settings
        # We need to ensure ServiceConstants has the required attributes
        try:
            from src.services.service_constants import ServiceConstants
            ServiceConstants.INITIAL_LOOKBACK_DAYS = 30
            ServiceConstants.ASANA_SYNC_INTERVAL = 3600
        except ImportError:
            # If import fails (shouldn't if mocked globally), we can mock it here or rely on global mock
            pass
            
        crawler = AsanaCrawler(config=config, user_id=1, asana_service=MagicMock())
        return crawler

    def test_extract_asana_custom_fields_simple(self, asana_crawler):
        """Test extraction of simple Asana custom fields."""
        custom_fields = [
            {"name": "Priority", "type": "enum", "enum_value": {"name": "High"}},
            {"name": "Effort", "type": "number", "number_value": 5},
            {"name": "Summary", "type": "text", "text_value": "Short summary"}
        ]
        
        schema_props = asana_crawler._extract_custom_fields(custom_fields)
        
        assert schema_props["Priority"] == "High"
        assert schema_props["Effort"] == 5
        assert schema_props["Summary"] == "Short summary"

    def test_extract_asana_custom_fields_complex(self, asana_crawler):
        """Test extraction of complex Asana custom fields (Multi-enum, Date, People)."""
        custom_fields = [
            {
                "name": "Teams", 
                "type": "multi_enum", 
                "multi_enum_values": [{"name": "Dev"}, {"name": "Design"}]
            },
            {
                "name": "Launch", 
                "type": "date", 
                "date_value": {"date": "2023-12-01"}
            },
            {
                "name": "Reviewers",
                "type": "people",
                "people_value": [{"name": "Charlie"}, {"name": "Dave"}]
            }
        ]
        
        schema_props = asana_crawler._extract_custom_fields(custom_fields)
        
        assert schema_props["Teams"] == ["Dev", "Design"]
        assert schema_props["Launch"] == "2023-12-01"
        assert schema_props["Reviewers"] == ["Charlie", "Dave"]

    def test_extract_asana_custom_fields_fallback(self, asana_crawler):
        """Test fallback to display_value for unknown types."""
        custom_fields = [
            {
                "name": "Unknown Field",
                "type": "strange_type",
                "display_value": "Fallback Value"
            }
        ]
        
        schema_props = asana_crawler._extract_custom_fields(custom_fields)
        
        assert schema_props["Unknown Field"] == "Fallback Value"

    def test_extract_asana_custom_fields_empty(self, asana_crawler):
        """Test that empty values are skipped."""
        custom_fields = [
            {"name": "Empty Text", "type": "text", "text_value": None},
            {"name": "Empty Enum", "type": "enum", "enum_value": None}
        ]
        
        schema_props = asana_crawler._extract_custom_fields(custom_fields)
        
        assert schema_props == {}


class TestVectorMetadataExtraction:
    """Tests for _extract_searchable_metadata in GraphRAGIntegrationService.
    
    Verifies Gap 1 fix: schema_properties and source fields flow into Qdrant metadata.
    """

    @pytest.fixture
    def integration_service(self):
        """Create a minimal GraphRAGIntegrationService with mocked dependencies.
        
        Uses object.__new__ to bypass __init__ type validation since we only
        need to test _extract_searchable_metadata, not the full service.
        """
        from src.services.indexing.rag_graph_bridge import GraphRAGIntegrationService
        service = object.__new__(GraphRAGIntegrationService)
        service.rag = MagicMock()
        service.graph = MagicMock()
        return service

    def test_notion_source_fields_in_metadata(self, integration_service):
        """Test that Notion source fields are included in vector metadata."""
        from src.services.indexing.parsers.base import ParsedNode
        
        node = ParsedNode(
            node_id="notion_page_abc123",
            node_type="document",
            properties={
                'title': 'Sprint Planning',
                'filename': 'Sprint Planning',
                'source': 'notion',
                'doc_type': 'notion_page',
                'notion_page_id': 'abc-123',
                'notion_database_id': 'db-456',
                'user_id': 1,
                'schema_properties': {
                    'Status': 'In Progress',
                    'Priority': 'High',
                    'Cost': 100,
                    'Tags': ['dev', 'sprint'],  # List - should be skipped in flattening
                }
            },
            searchable_text="Sprint Planning document"
        )
        
        metadata = integration_service._extract_searchable_metadata(node)
        
        # Source fields should be present
        assert metadata['source'] == 'notion'
        assert metadata['doc_type'] == 'notion_page'
        assert metadata['notion_page_id'] == 'abc-123'
        assert metadata['notion_database_id'] == 'db-456'
        assert metadata['user_id'] == 1
        
        # Flattened schema_properties with sp_ prefix (simple types only)
        assert metadata['sp_Status'] == 'In Progress'
        assert metadata['sp_Priority'] == 'High'
        assert metadata['sp_Cost'] == 100
        # Lists should NOT be flattened
        assert 'sp_Tags' not in metadata

    def test_asana_source_fields_in_metadata(self, integration_service):
        """Test that Asana source fields are included in vector metadata."""
        from src.services.indexing.parsers.base import ParsedNode
        
        node = ParsedNode(
            node_id="asana_task_789",
            node_type="action_item",
            properties={
                'description': 'Fix login bug',
                'source': 'asana',
                'asana_task_id': '789',
                'status': 'pending',
                'priority': 'high',
                'completed': False,
                'user_id': 1,
                'schema_properties': {
                    'Sprint': 'Sprint 5',
                    'Story Points': 3,
                    'Blocked': True,
                }
            },
            searchable_text="Fix login bug"
        )
        
        metadata = integration_service._extract_searchable_metadata(node)
        
        # Source fields
        assert metadata['source'] == 'asana'
        assert metadata['asana_task_id'] == '789'
        assert metadata['status'] == 'pending'
        assert metadata['priority'] == 'high'
        assert metadata['completed'] is False
        
        # Flattened schema_properties
        assert metadata['sp_Sprint'] == 'Sprint 5'
        assert metadata['sp_Story Points'] == 3
        assert metadata['sp_Blocked'] is True

    def test_no_schema_properties_is_safe(self, integration_service):
        """Test that nodes without schema_properties don't cause errors."""
        from src.services.indexing.parsers.base import ParsedNode
        
        node = ParsedNode(
            node_id="email_123",
            node_type="email",
            properties={
                'subject': 'Hello',
                'user_id': 1,
            },
            searchable_text="Hello email"
        )
        
        metadata = integration_service._extract_searchable_metadata(node)
        
        assert metadata['user_id'] == 1
        # No sp_ keys should exist
        assert not any(k.startswith('sp_') for k in metadata)

    def test_empty_schema_properties_is_safe(self, integration_service):
        """Test that empty schema_properties dict doesn't cause errors."""
        from src.services.indexing.parsers.base import ParsedNode
        
        node = ParsedNode(
            node_id="notion_page_empty",
            node_type="document",
            properties={
                'filename': 'Empty Page',
                'source': 'notion',
                'user_id': 1,
                'schema_properties': {}
            },
            searchable_text="Empty page"
        )
        
        metadata = integration_service._extract_searchable_metadata(node)
        
        assert metadata['source'] == 'notion'
        assert not any(k.startswith('sp_') for k in metadata)

