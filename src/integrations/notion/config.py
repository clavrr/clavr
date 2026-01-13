"""
Notion Integration Configuration

Configuration for Notion integration using environment variables.
No hardcoded values - all configuration comes from environment.
"""
import os
from typing import Optional
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionConfig:
    """Notion integration configuration"""
    
    # Notion API Configuration
    NOTION_API_KEY: Optional[str] = os.getenv('NOTION_API_KEY')  # Notion integration token
    NOTION_DATABASE_ID: Optional[str] = os.getenv('NOTION_DATABASE_ID')  # Main database ID
    NOTION_API_VERSION: str = os.getenv('NOTION_API_VERSION', '2022-06-28')  # API version
    
    # Notion Workspace Configuration
    WORKSPACE_ID: Optional[str] = os.getenv('NOTION_WORKSPACE_ID')
    
    # Feature Flags
    ENABLE_KNOWLEDGE_CAPTURE: bool = os.getenv('NOTION_ENABLE_KNOWLEDGE_CAPTURE', 'true').lower() == 'true'
    ENABLE_AUTONOMOUS_EXECUTION: bool = os.getenv('NOTION_ENABLE_AUTONOMOUS_EXECUTION', 'true').lower() == 'true'
    ENABLE_AUTOMATION: bool = os.getenv('NOTION_ENABLE_AUTOMATION', 'true').lower() == 'true'
    
    # Sync Configuration
    SYNC_INTERVAL_SECONDS: int = int(os.getenv('NOTION_SYNC_INTERVAL_SECONDS', '300'))  # 5 minutes
    MAX_RETRIES: int = int(os.getenv('NOTION_MAX_RETRIES', '3'))
    RETRY_DELAY_SECONDS: int = int(os.getenv('NOTION_RETRY_DELAY_SECONDS', '5'))
    
    @classmethod
    def validate(cls) -> bool:
        """
        Validate that required Notion configuration is present.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        missing = []
        
        if not cls.NOTION_API_KEY:
            missing.append('NOTION_API_KEY')
        
        if not cls.NOTION_DATABASE_ID:
            missing.append('NOTION_DATABASE_ID')
        
        if missing:
            logger.error(f"Missing required Notion configuration: {', '.join(missing)}")
            logger.error("Please set the following environment variables:")
            for var in missing:
                logger.error(f"  - {var}")
            return False
        
        # Validate token format
        if cls.NOTION_API_KEY and not cls.NOTION_API_KEY.startswith('notioneye-'):
            logger.warning(f"NOTION_API_KEY should start with 'notioneye-' (got: {cls.NOTION_API_KEY[:20]}...)")
        
        logger.info("Notion configuration validated successfully")
        return True
    
    @classmethod
    def get_config_dict(cls) -> dict:
        """Get configuration as dictionary"""
        return {
            'api_key': cls.NOTION_API_KEY,
            'database_id': cls.NOTION_DATABASE_ID,
            'api_version': cls.NOTION_API_VERSION,
            'workspace_id': cls.WORKSPACE_ID,
            'enable_knowledge_capture': cls.ENABLE_KNOWLEDGE_CAPTURE,
            'enable_autonomous_execution': cls.ENABLE_AUTONOMOUS_EXECUTION,
            'enable_automation': cls.ENABLE_AUTOMATION,
            'sync_interval_seconds': cls.SYNC_INTERVAL_SECONDS,
            'max_retries': cls.MAX_RETRIES,
            'retry_delay_seconds': cls.RETRY_DELAY_SECONDS,
        }
