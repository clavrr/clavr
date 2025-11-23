"""
Slack Integration Configuration

Configuration for Slack integration using environment variables.
No hardcoded values - all configuration comes from environment.
"""
import os
from typing import Optional
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class SlackConfig:
    """Slack integration configuration"""
    
    # Socket Mode Configuration
    SLACK_APP_TOKEN: Optional[str] = os.getenv('SLACK_APP_TOKEN')  # xapp-* token
    SLACK_BOT_TOKEN: Optional[str] = os.getenv('SLACK_BOT_TOKEN')  # xoxb-* token or xoxe.xoxp-* (token rotation)
    
    # Bot Configuration
    BOT_NAME: str = os.getenv('SLACK_BOT_NAME', 'clavr')
    BOT_USER_ID: Optional[str] = os.getenv('SLACK_BOT_USER_ID')
    
    # Workspace Configuration
    WORKSPACE_ID: Optional[str] = os.getenv('SLACK_WORKSPACE_ID')
    
    @classmethod
    def validate(cls) -> bool:
        """
        Validate that required Slack configuration is present.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        missing = []
        
        if not cls.SLACK_APP_TOKEN:
            missing.append('SLACK_APP_TOKEN')
        
        if not cls.SLACK_BOT_TOKEN:
            missing.append('SLACK_BOT_TOKEN')
        
        if missing:
            logger.error(f"Missing required Slack configuration: {', '.join(missing)}")
            logger.error("Please set the following environment variables:")
            for var in missing:
                logger.error(f"  - {var}")
            return False
        
        # Validate token formats (only if tokens are present)
        if cls.SLACK_APP_TOKEN and not cls.SLACK_APP_TOKEN.startswith('xapp-'):
            token_preview = cls.SLACK_APP_TOKEN[:10] if cls.SLACK_APP_TOKEN else 'None'
            logger.warning(f"SLACK_APP_TOKEN should start with 'xapp-' (got: {token_preview}...)")
        
        if cls.SLACK_BOT_TOKEN:
            # Accept both regular bot tokens (xoxb-*) and token rotation tokens (xoxe.xoxp-*)
            is_valid_bot_token = (
                cls.SLACK_BOT_TOKEN.startswith('xoxb-') or 
                cls.SLACK_BOT_TOKEN.startswith('xoxe.xoxp-')
            )
            if not is_valid_bot_token:
                token_preview = cls.SLACK_BOT_TOKEN[:10] if cls.SLACK_BOT_TOKEN else 'None'
                logger.warning(
                    f"SLACK_BOT_TOKEN should start with 'xoxb-' (regular) or 'xoxe.xoxp-' (token rotation) "
                    f"(got: {token_preview}...)"
                )
            elif cls.SLACK_BOT_TOKEN.startswith('xoxe.xoxp-'):
                logger.info("Using Slack token rotation token (xoxe.xoxp-*)")
        
        logger.info("Slack configuration validated successfully")
        return True
    
    @classmethod
    def get_config_dict(cls) -> dict:
        """Get configuration as dictionary"""
        return {
            'app_token': cls.SLACK_APP_TOKEN,
            'bot_token': cls.SLACK_BOT_TOKEN,
            'bot_name': cls.BOT_NAME,
            'bot_user_id': cls.BOT_USER_ID,
            'workspace_id': cls.WORKSPACE_ID
        }

