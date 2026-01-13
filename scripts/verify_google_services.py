#!/usr/bin/env python3
print("DEBUG: Script started")
import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.config import load_config
from src.database.database import get_session_local
from src.database.models import Session, User
from src.core.email.google_client import GoogleGmailClient
from src.core.calendar.google_client import GoogleCalendarClient
from src.utils.encryption import decrypt_token
from google.oauth2.credentials import Credentials
from sqlalchemy import desc

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def verify_google_services():
    logger.info("Starting Google Services Verification...")
    
    # 1. Load Config
    try:
        config = load_config()
        logger.info("Configuration loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return

    # 2. Get Database Session
    try:
        db = get_session_local()()
        logger.info("Database connection established.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return

    # 3. Find active session with Google tokens
    try:
        # Get the most recent session with a refresh token
        session = db.query(Session).filter(
            Session.gmail_refresh_token.isnot(None)
        ).order_by(desc(Session.last_active_at)).first()

        if not session:
            logger.warning("No active session with Google credentials found in the database.")
            logger.warning("Please log in to the application first to generate a session.")
            return

        user = db.query(User).filter(User.id == session.user_id).first()
        if user:
            logger.info(f"Found active session for user: {user.email}")
        else:
            logger.warning(f"Found session but user not found (User ID: {session.user_id})")

        # 4. Construct Credentials
        # We need client config from Config or Env
        client_id = config.oauth.providers['google'].client_id if config.oauth and 'google' in config.oauth.providers else os.getenv('GOOGLE_CLIENT_ID')
        client_secret = config.oauth.providers['google'].client_secret if config.oauth and 'google' in config.oauth.providers else os.getenv('GOOGLE_CLIENT_SECRET')
        token_uri = config.oauth.providers['google'].token_url if config.oauth and 'google' in config.oauth.providers else "https://oauth2.googleapis.com/token"

        if not client_id or not client_secret:
            logger.error("Missing Google Client ID or Secret in configuration.")
            return

        # Decrypt tokens
        try:
            access_token = decrypt_token(session.gmail_access_token)
            refresh_token = decrypt_token(session.gmail_refresh_token)
        except Exception as e:
            logger.error(f"Failed to decrypt tokens: {e}")
            return

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=None  # Providing scopes here is optional and caused issues when passing raw token
        )
        
        # Check if creds are valid (authorized)
        # Note: We rely on the client to refresh if needed.

    except Exception as e:
        logger.error(f"Error retrieving credentials: {e}")
        return
    finally:
        db.close()

    # 5. Verify Gmail
    try:
        logger.info("Verifying Gmail Service...")
        gmail_client = GoogleGmailClient(config, credentials=creds)
        if not gmail_client.is_available():
             logger.warning("Gmail client reports unavailability (missing creds?).")
        
        # Test call
        messages = gmail_client.list_messages(max_results=5)
        logger.info(f"✅ GMAIL SUCCESS: Retrieved {len(messages)} messages.")
        for msg in messages:
            logger.info(f"   - [{msg.get('date')}] {msg.get('subject')[:50]}...")

    except Exception as e:
        logger.error(f"❌ GMAIL FAILED: {e}")

    # 6. Verify Calendar
    try:
        logger.info("Verifying Calendar Service...")
        # Note: GoogleCalendarClient likely has similar interface
        calendar_client = GoogleCalendarClient(config, credentials=creds)
        
        # Test call
        events = calendar_client.list_events(max_results=5)
        logger.info(f"✅ CALENDAR SUCCESS: Retrieved {len(events)} events.")
        for event in events:
             start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
             logger.info(f"   - [{start}] {event.get('summary', 'No Title')}")

    except Exception as e:
        logger.error(f"❌ CALENDAR FAILED: {e}")

    # 7. Verify Keep
    try:
        logger.info("Verifying Keep Service...")
        from src.core.keep.google_client import GoogleKeepClient
        keep_client = GoogleKeepClient(config, credentials=creds)
        
        # Test call
        notes = keep_client.list_notes(page_size=5)
        logger.info(f"✅ KEEP SUCCESS: Retrieved {len(notes)} notes.")
        for note in notes:
             logger.info(f"   - {note.get('title', 'No Title')[:40]}")

    except Exception as e:
        # Check for specific 403 error that might indicate enterprise requirement
        if "403" in str(e) and "enterprise" in str(e).lower():
             logger.warning(f"⚠️ KEEP WARNING: Access restricted (Likely requires Workspace Enterprise). Error: {e}")
        else:
             logger.error(f"❌ KEEP FAILED: {e}")

if __name__ == "__main__":
    verify_google_services()
