"""
Tests for GDPR-Compliant Data Export Feature

Test coverage:
- Data export service functionality
- API endpoints for export requests
- Export formats (JSON, CSV, ZIP)
- Security and access control
- GDPR compliance requirements
"""

import pytest
import json
import zipfile
import io
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from sqlalchemy.orm import Session

# Mock problematic imports before importing our modules
sys.modules['src.ai'] = MagicMock()
sys.modules['src.ai.llm_factory'] = MagicMock()
sys.modules['src.features.base_feature'] = MagicMock()

from src.features.data_export import DataExportService, generate_export_for_user
from src.database.models import User, UserSettings, Session as SessionModel, ConversationMessage


# Fixtures

@pytest.fixture
def mock_config():
    """Mock configuration"""
    config = Mock()
    config.database = Mock()
    config.database.url = "sqlite:///test.db"
    return config


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    return db


@pytest.fixture
def sample_user():
    """Sample user for testing"""
    user = User(
        id=1,
        google_id="test_google_id",
        email="test@example.com",
        name="Test User",
        picture_url="https://example.com/pic.jpg",
        created_at=datetime.utcnow(),
        email_indexed=True,
        index_count=100,
        indexing_status="completed",
        is_admin=False,
        collection_name="user_1_collection"
    )
    return user


@pytest.fixture
def sample_settings(sample_user):
    """Sample user settings"""
    settings = UserSettings(
        id=1,
        user_id=sample_user.id,
        email_notifications=True,
        push_notifications=False,
        dark_mode=True,
        language="en",
        region="US",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    return settings


@pytest.fixture
def sample_session(sample_user):
    """Sample session"""
    session = SessionModel(
        id=1,
        user_id=sample_user.id,
        session_token="hashed_token",
        gmail_access_token="access_token",
        gmail_refresh_token="refresh_token",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    return session


@pytest.fixture
def sample_conversations(sample_user):
    """Sample conversation messages"""
    messages = [
        ConversationMessage(
            id=1,
            user_id=sample_user.id,
            session_id="session_1",
            role="user",
            content="Hello!",
            intent="greeting",
            entities={},
            confidence="high",
            timestamp=datetime.utcnow()
        ),
        ConversationMessage(
            id=2,
            user_id=sample_user.id,
            session_id="session_1",
            role="assistant",
            content="Hi! How can I help you?",
            intent="greeting_response",
            entities={},
            confidence="high",
            timestamp=datetime.utcnow()
        )
    ]
    return messages


# DataExportService Tests

class TestDataExportService:
    """Test DataExportService class"""
    
    def test_init(self, mock_db, mock_config):
        """Test service initialization"""
        service = DataExportService(mock_db, mock_config)
        assert service.db == mock_db
        assert service.config == mock_config
    
    def test_get_export_metadata(self, mock_db, mock_config, sample_user):
        """Test export metadata generation"""
        service = DataExportService(mock_db, mock_config)
        metadata = service._get_export_metadata(sample_user)
        
        assert metadata["user_id"] == sample_user.id
        assert metadata["user_email"] == sample_user.email
        assert metadata["data_controller"] == "Notely Agent"
        assert "GDPR" in metadata["gdpr_compliance"]
        assert metadata["format_version"] == "1.0"
        assert "export_date" in metadata
    
    @pytest.mark.asyncio
    async def test_export_user_profile(self, mock_db, mock_config, sample_user):
        """Test user profile export"""
        service = DataExportService(mock_db, mock_config)
        profile = await service._export_user_profile(sample_user)
        
        assert profile["user_id"] == sample_user.id
        assert profile["email"] == sample_user.email
        assert profile["name"] == sample_user.name
        assert profile["google_id"] == sample_user.google_id
        assert profile["indexing_status"]["email_indexed"] == True
        assert profile["indexing_status"]["index_count"] == 100
        assert profile["collection_name"] == "user_1_collection"
    
    @pytest.mark.asyncio
    async def test_export_user_settings(self, mock_db, mock_config, sample_user, sample_settings):
        """Test user settings export"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_settings
        
        service = DataExportService(mock_db, mock_config)
        settings = await service._export_user_settings(sample_user)
        
        assert settings is not None
        assert settings["email_notifications"] == True
        assert settings["push_notifications"] == False
        assert settings["dark_mode"] == True
        assert settings["language"] == "en"
        assert settings["region"] == "US"
    
    @pytest.mark.asyncio
    async def test_export_user_settings_none(self, mock_db, mock_config, sample_user):
        """Test user settings export when no settings exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        service = DataExportService(mock_db, mock_config)
        settings = await service._export_user_settings(sample_user)
        
        assert settings is None
    
    @pytest.mark.asyncio
    async def test_export_sessions(self, mock_db, mock_config, sample_user, sample_session):
        """Test session history export"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [sample_session]
        
        service = DataExportService(mock_db, mock_config)
        sessions = await service._export_sessions(sample_user)
        
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == sample_session.id
        assert sessions[0]["has_gmail_access"] == True
        assert "session_token" not in sessions[0]  # Security: tokens excluded
        assert "gmail_access_token" not in sessions[0]
    
    @pytest.mark.asyncio
    async def test_export_conversations(self, mock_db, mock_config, sample_user, sample_conversations):
        """Test conversation history export"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = sample_conversations
        
        service = DataExportService(mock_db, mock_config)
        messages = await service._export_conversations(sample_user)
        
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello!"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi! How can I help you?"
    
    def test_flatten_dict(self, mock_db, mock_config):
        """Test dictionary flattening for CSV export"""
        service = DataExportService(mock_db, mock_config)
        
        nested = {
            "name": "Test",
            "address": {
                "street": "123 Main St",
                "city": "Springfield"
            },
            "tags": ["tag1", "tag2"]
        }
        
        flattened = service._flatten_dict(nested)
        
        assert flattened["name"] == "Test"
        assert flattened["address_street"] == "123 Main St"
        assert flattened["address_city"] == "Springfield"
        assert json.loads(flattened["tags"]) == ["tag1", "tag2"]
    
    def test_dict_to_csv(self, mock_db, mock_config):
        """Test CSV conversion"""
        service = DataExportService(mock_db, mock_config)
        
        data = [
            {"name": "Alice", "age": 30, "city": "NYC"},
            {"name": "Bob", "age": 25, "city": "LA"}
        ]
        
        csv_output = service._dict_to_csv(data)
        
        assert "name" in csv_output
        assert "Alice" in csv_output
        assert "Bob" in csv_output
        assert csv_output.count("\n") >= 3  # Header + 2 rows
    
    def test_dict_to_csv_empty(self, mock_db, mock_config):
        """Test CSV conversion with empty data"""
        service = DataExportService(mock_db, mock_config)
        csv_output = service._dict_to_csv([])
        assert csv_output == ""
    
    def test_generate_readme(self, mock_db, mock_config, sample_user):
        """Test README generation"""
        service = DataExportService(mock_db, mock_config)
        readme = service._generate_readme(sample_user)
        
        assert "NOTELY AGENT" in readme
        assert sample_user.email in readme
        assert str(sample_user.id) in readme
        assert "GDPR" in readme
        assert "Article 20" in readme
        assert "complete_export.json" in readme
    
    @pytest.mark.asyncio
    async def test_create_zip_archive(self, mock_db, mock_config, sample_user):
        """Test ZIP archive creation"""
        service = DataExportService(mock_db, mock_config)
        
        test_data = {
            "user_profile": {"name": "Test User"},
            "sessions": [{"id": 1}],
            "conversation_history": []
        }
        
        zip_bytes = service._create_zip_archive(test_data, sample_user)
        
        assert isinstance(zip_bytes, bytes)
        assert len(zip_bytes) > 0
        
        # Verify ZIP structure
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
            files = zip_file.namelist()
            assert "complete_export.json" in files
            assert "README.txt" in files
            
            # Verify JSON content
            json_content = zip_file.read("complete_export.json")
            loaded_data = json.loads(json_content)
            assert loaded_data["user_profile"]["name"] == "Test User"


# Export Format Tests

class TestExportFormats:
    """Test different export formats"""
    
    @pytest.mark.asyncio
    @patch('src.features.data_export.DataExportService._export_emails')
    @patch('src.features.data_export.DataExportService._export_calendar')
    @patch('src.features.data_export.DataExportService._export_tasks')
    async def test_json_export(self, mock_tasks, mock_calendar, mock_emails, mock_db, mock_config, sample_user):
        """Test JSON export format"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        mock_emails.return_value = {"status": "success", "emails": []}
        mock_calendar.return_value = {"status": "success", "events": []}
        mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
        
        service = DataExportService(mock_db, mock_config)
        result = await service.export_user_data(user_id=sample_user.id, format="json")
        
        assert isinstance(result, dict)
        assert "export_metadata" in result
        assert "user_profile" in result
        assert "emails" in result
        assert "calendar_events" in result
    
    @pytest.mark.asyncio
    @patch('src.features.data_export.DataExportService._export_emails')
    @patch('src.features.data_export.DataExportService._export_calendar')
    @patch('src.features.data_export.DataExportService._export_tasks')
    async def test_csv_export(self, mock_tasks, mock_calendar, mock_emails, mock_db, mock_config, sample_user):
        """Test CSV export format"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        mock_emails.return_value = {"status": "success", "emails": [{"id": 1, "subject": "Test"}]}
        mock_calendar.return_value = {"status": "success", "events": [{"id": 1, "summary": "Meeting"}]}
        mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
        
        service = DataExportService(mock_db, mock_config)
        result = await service.export_user_data(user_id=sample_user.id, format="csv")
        
        assert isinstance(result, dict)
        # Should contain CSV files as strings
        for key, value in result.items():
            if value:  # Skip empty CSV files
                assert isinstance(value, str)
    
    @pytest.mark.asyncio
    @patch('src.features.data_export.DataExportService._export_emails')
    @patch('src.features.data_export.DataExportService._export_calendar')
    @patch('src.features.data_export.DataExportService._export_tasks')
    async def test_zip_export(self, mock_tasks, mock_calendar, mock_emails, mock_db, mock_config, sample_user):
        """Test ZIP export format"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        mock_emails.return_value = {"status": "success", "emails": []}
        mock_calendar.return_value = {"status": "success", "events": []}
        mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
        
        service = DataExportService(mock_db, mock_config)
        result = await service.export_user_data(user_id=sample_user.id, format="zip")
        
        assert isinstance(result, bytes)
        
        # Verify it's a valid ZIP file
        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
            assert len(zip_file.namelist()) > 0


# Security Tests

class TestDataExportSecurity:
    """Test security aspects of data export"""
    
    @pytest.mark.asyncio
    async def test_user_not_found(self, mock_db, mock_config):
        """Test export fails for non-existent user"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        service = DataExportService(mock_db, mock_config)
        
        with pytest.raises(ValueError, match="User .* not found"):
            await service.export_user_data(user_id=999, format="json")
    
    @pytest.mark.asyncio
    async def test_session_tokens_excluded(self, mock_db, mock_config, sample_user, sample_session):
        """Test that sensitive session tokens are excluded from export"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [sample_session]
        
        service = DataExportService(mock_db, mock_config)
        sessions = await service._export_sessions(sample_user)
        
        # Verify sensitive data is excluded
        for session in sessions:
            assert "session_token" not in session
            assert "gmail_access_token" not in session
            assert "gmail_refresh_token" not in session
    
    @pytest.mark.asyncio
    async def test_invalid_format(self, mock_db, mock_config, sample_user):
        """Test export fails with invalid format"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        
        service = DataExportService(mock_db, mock_config)
        
        with pytest.raises(ValueError, match="Unsupported format"):
            await service.export_user_data(user_id=sample_user.id, format="invalid")


# GDPR Compliance Tests

class TestGDPRCompliance:
    """Test GDPR compliance requirements"""
    
    @pytest.mark.asyncio
    async def test_export_contains_all_personal_data(self, mock_db, mock_config, sample_user):
        """Test that export includes all categories of personal data"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        
        with patch('src.features.data_export.DataExportService._export_emails') as mock_emails, \
             patch('src.features.data_export.DataExportService._export_calendar') as mock_calendar, \
             patch('src.features.data_export.DataExportService._export_tasks') as mock_tasks:
            
            mock_emails.return_value = {"status": "success", "emails": []}
            mock_calendar.return_value = {"status": "success", "events": []}
            mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
            
            service = DataExportService(mock_db, mock_config)
            result = await service.export_user_data(user_id=sample_user.id, format="json")
            
            # Verify all required data categories are present
            required_categories = [
                "export_metadata",
                "user_profile",
                "user_settings",
                "sessions",
                "conversation_history",
                "emails",
                "calendar_events",
                "tasks"
            ]
            
            for category in required_categories:
                assert category in result, f"Missing required category: {category}"
    
    @pytest.mark.asyncio
    async def test_export_metadata_includes_gdpr_info(self, mock_db, mock_config, sample_user):
        """Test that export metadata includes GDPR compliance information"""
        service = DataExportService(mock_db, mock_config)
        metadata = service._get_export_metadata(sample_user)
        
        assert "gdpr_compliance" in metadata
        assert "Article 20" in metadata["gdpr_compliance"]
        assert "export_date" in metadata
        assert "data_controller" in metadata
    
    @pytest.mark.asyncio
    async def test_machine_readable_format(self, mock_db, mock_config, sample_user):
        """Test that exports are in machine-readable formats"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        
        with patch('src.features.data_export.DataExportService._export_emails') as mock_emails, \
             patch('src.features.data_export.DataExportService._export_calendar') as mock_calendar, \
             patch('src.features.data_export.DataExportService._export_tasks') as mock_tasks:
            
            mock_emails.return_value = {"status": "success", "emails": []}
            mock_calendar.return_value = {"status": "success", "events": []}
            mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
            
            service = DataExportService(mock_db, mock_config)
            
            # Test JSON (machine-readable)
            json_result = await service.export_user_data(user_id=sample_user.id, format="json")
            assert isinstance(json_result, dict)
            # Should be serializable
            json.dumps(json_result, default=str)
            
            # Test CSV (machine-readable and portable)
            csv_result = await service.export_user_data(user_id=sample_user.id, format="csv")
            assert isinstance(csv_result, dict)


# Integration Tests

class TestDataExportIntegration:
    """Integration tests for data export"""
    
    @pytest.mark.asyncio
    @patch('src.features.data_export.get_vector_store')
    async def test_complete_export_workflow(self, mock_vector_store, mock_db, mock_config, sample_user):
        """Test complete export workflow"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user
        mock_vector_store.return_value.get_stats.return_value = {"count": 100}
        
        with patch('src.features.data_export.DataExportService._export_emails') as mock_emails, \
             patch('src.features.data_export.DataExportService._export_calendar') as mock_calendar, \
             patch('src.features.data_export.DataExportService._export_tasks') as mock_tasks:
            
            mock_emails.return_value = {"status": "success", "emails": []}
            mock_calendar.return_value = {"status": "success", "events": []}
            mock_tasks.return_value = {"status": "not_implemented", "tasks": []}
            
            # Test the convenience function
            result = await generate_export_for_user(
                user_id=sample_user.id,
                db=mock_db,
                config=mock_config,
                format="json"
            )
            
            assert isinstance(result, dict)
            assert result["export_metadata"]["user_id"] == sample_user.id
