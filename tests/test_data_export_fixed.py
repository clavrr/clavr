"""
Tests for GDPR-Compliant Data Export Feature (Fixed Version)

This version uses proper mocking to avoid dependency issues.
"""

import pytest
import json
import zipfile
import io
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path

# Mock problematic dependencies BEFORE any imports
sys.modules['langchain_google_genai'] = MagicMock()
sys.modules['langchain_core'] = MagicMock()
sys.modules['langchain_core.language_models'] = MagicMock()
sys.modules['langchain_core.language_models.base'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['sentence_transformers'] = MagicMock()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from src.database.models import User, UserSettings, Session as SessionModel, ConversationMessage

# Now we can safely import our module
from src.features.data_export import DataExportService, generate_export_for_user
from src.utils.config import Config


# Fixtures

@pytest.fixture
def mock_config():
    """Mock configuration"""
    config = Mock(spec=Config)
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


# Tests

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
        assert profile["indexing_status"]["email_indexed"] == True
    
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
    
    def test_dict_to_csv(self, mock_db, mock_config):
        """Test CSV conversion"""
        service = DataExportService(mock_db, mock_config)
        
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25}
        ]
        
        csv_output = service._dict_to_csv(data)
        
        assert "name" in csv_output
        assert "Alice" in csv_output
        assert "Bob" in csv_output
    
    def test_generate_readme(self, mock_db, mock_config, sample_user):
        """Test README generation"""
        service = DataExportService(mock_db, mock_config)
        readme = service._generate_readme(sample_user)
        
        assert "NOTELY AGENT" in readme
        assert sample_user.email in readme
        assert "GDPR" in readme
    
    @pytest.mark.asyncio
    async def test_user_not_found(self, mock_db, mock_config):
        """Test export fails for non-existent user"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        service = DataExportService(mock_db, mock_config)
        
        with pytest.raises(ValueError, match="User .* not found"):
            await service.export_user_data(user_id=999, format="json")


class TestGDPRCompliance:
    """Test GDPR compliance"""
    
    def test_export_metadata_includes_gdpr_info(self, mock_db, mock_config, sample_user):
        """Test GDPR compliance information"""
        service = DataExportService(mock_db, mock_config)
        metadata = service._get_export_metadata(sample_user)
        
        assert "gdpr_compliance" in metadata
        assert "Article 20" in metadata["gdpr_compliance"]
        assert "data_controller" in metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
