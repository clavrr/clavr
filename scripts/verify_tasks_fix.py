#!/usr/bin/env python3
"""
Verify Tasks Scope Fix
Tests that AppState correctly fetches integration-specific credentials for Tasks
and that refreshing these credentials doesn't cause an invalid_scope error.
"""
import os
import sys
import logging
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.config import load_config
from src.database.database import get_session_local
from src.database.models import User, UserIntegration, Session
from api.dependencies import AppState
from google.auth.transport.requests import Request

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def verify_fix():
    logger.info("Starting Tasks Scope Fix Verification...")
    
    # 1. Load Config
    config = load_config()
    AppState._config = config
    
    # 2. Find a user with a tasks integration
    db = get_session_local()()
    try:
        integration = db.query(UserIntegration).filter(
            UserIntegration.provider == 'google_tasks',
            UserIntegration.is_active == True
        ).first()
        
        if not integration:
            logger.warning("No active Google Tasks integration found in UserIntegration table.")
            return
            
        user_id = integration.user_id
        user = db.query(User).filter(User.id == user_id).first()
        logger.info(f"Testing fix for user: {user.email} (ID: {user_id})")
        
        # 3. Get Task Tool via AppState
        logger.info("Fetching task tool via AppState...")
        task_tool = AppState.get_task_tool(user_id=user_id)
        
        if not task_tool.credentials:
            logger.error("Failed to get credentials for Task Tool.")
            return
            
        logger.info(f"Successfully obtained credentials for Task Tool.")
        logger.info(f"Target Scopes: {task_tool.credentials.scopes}")
        
        # 4. Verify refreshing doesn't cause invalid_scope
        if task_tool.credentials.refresh_token:
            logger.info("Attempting to refresh credentials...")
            try:
                task_tool.credentials.refresh(Request())
                logger.info("✅ SUCCESS: Credentials refreshed successfully!")
            except Exception as e:
                if "invalid_scope" in str(e):
                    logger.error(f"❌ FAILURE: Credentials refresh failed with invalid_scope error: {e}")
                else:
                    logger.warning(f"Refresh failed (might be expired or network): {e}")
        else:
            logger.warning("No refresh token available, skipping refresh test.")
            
        # 5. Check consistency
        from src.core.credential_provider import CredentialProvider
        check_creds = CredentialProvider.get_integration_credentials(user_id, 'google_tasks')
        
        if check_creds and check_creds.token == task_tool.credentials.token:
            logger.info("✅ SUCCESS: Verified that Task tool is using integration-specific tokens.")
        else:
            logger.warning("Tool is using different credentials than those in UserIntegration table.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(verify_fix())
