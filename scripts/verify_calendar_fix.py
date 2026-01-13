#!/usr/bin/env python3
"""
Verify Calendar Scope Fix
Tests that AppState correctly fetches integration-specific credentials for Calendar
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
    logger.info("Starting Calendar Scope Fix Verification...")
    
    # 1. Load Config
    config = load_config()
    AppState._config = config
    
    # 2. Find a user with a calendar integration
    db = get_session_local()()
    try:
        integration = db.query(UserIntegration).filter(
            UserIntegration.provider == 'google_calendar',
            UserIntegration.is_active == True
        ).first()
        
        if not integration:
            logger.warning("No active Google Calendar integration found in UserIntegration table.")
            return
            
        user_id = integration.user_id
        user = db.query(User).filter(User.id == user_id).first()
        logger.info(f"Testing fix for user: {user.email} (ID: {user_id})")
        
        # 3. Get Calendar Tool via AppState (this triggers _get_credentials)
        # We simulate a request by passing None for request, it should hit database integrations
        logger.info("Fetching calendar tool via AppState...")
        calendar_tool = AppState.get_calendar_tool(user_id=user_id)
        
        if not calendar_tool.credentials:
            logger.error("Failed to get credentials for Calendar Tool.")
            return
            
        logger.info(f"Successfully obtained credentials for Calendar Tool.")
        logger.info(f"Target Scopes: {calendar_tool.credentials.scopes}")
        
        # 4. Verify refreshing doesn't cause invalid_scope
        # Note: We can't easily force a refresh if the token isn't expired, 
        # but we can call refresh() manually if we have a refresh token.
        if calendar_tool.credentials.refresh_token:
            logger.info("Attempting to refresh credentials (this will fail if scopes are invalid)...")
            try:
                calendar_tool.credentials.refresh(Request())
                logger.info("✅ SUCCESS: Credentials refreshed successfully!")
            except Exception as e:
                if "invalid_scope" in str(e):
                    logger.error(f"❌ FAILURE: Credentials refresh failed with invalid_scope error: {e}")
                else:
                    logger.warning(f"Refresh failed (might be network or stale token, but not invalid_scope): {e}")
        else:
            logger.warning("No refresh token available, skipping refresh test.")
            
        # 5. Check if we used the CORRECT provider tokens
        from src.core.credential_provider import CredentialProvider
        check_creds = CredentialProvider.get_integration_credentials(user_id, 'google_calendar')
        
        if check_creds and check_creds.token == calendar_tool.credentials.token:
            logger.info("✅ SUCCESS: Verified that Calendar tool is using integration-specific tokens.")
        else:
            logger.warning("Tool is using different credentials than those in UserIntegration table.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(verify_fix())
