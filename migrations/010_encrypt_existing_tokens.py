"""
Migration Script: Encrypt Existing Gmail Tokens

This script encrypts all existing Gmail access and refresh tokens in the database.
Run this ONCE after deploying the encryption changes.

Usage:
    python migrations/010_encrypt_existing_tokens.py

Requirements:
    - ENCRYPTION_KEY environment variable must be set
    - Database must be accessible
    - Backup database before running
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.utils.encryption import TokenEncryption
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def encrypt_existing_tokens():
    """
    Encrypt all existing Gmail tokens in the sessions table
    
    This is a one-time migration to encrypt tokens that were previously
    stored in plaintext.
    """
    # Get database URL
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Get encryption key
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if not encryption_key:
        logger.error("ENCRYPTION_KEY environment variable not set")
        logger.error("Generate a key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
        sys.exit(1)
    
    # Initialize encryption
    try:
        encryption = TokenEncryption(encryption_key)
        logger.info("[OK] Token encryption initialized")
    except Exception as e:
        logger.error(f"Failed to initialize encryption: {e}")
        sys.exit(1)
    
    # Connect to database
    try:
        engine = create_engine(database_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        logger.info("[OK] Connected to database")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)
    
    try:
        # Get all sessions with tokens
        result = db.execute(text("""
            SELECT id, gmail_access_token, gmail_refresh_token 
            FROM sessions 
            WHERE gmail_access_token IS NOT NULL
        """))
        
        sessions = result.fetchall()
        total = len(sessions)
        
        if total == 0:
            logger.info("No sessions found with tokens to encrypt")
            return
        
        logger.info(f"Found {total} sessions with tokens to encrypt")
        
        # Ask for confirmation
        response = input(f"\nEncrypt {total} Gmail tokens? This cannot be undone. (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Migration cancelled")
            return
        
        # Encrypt each session's tokens
        encrypted_count = 0
        skipped_count = 0
        error_count = 0
        
        for session_id, access_token, refresh_token in sessions:
            try:
                # Check if already encrypted (encrypted tokens are base64 and start with specific pattern)
                if access_token and len(access_token) > 100 and '=' in access_token[-5:]:
                    logger.debug(f"Session {session_id} appears already encrypted, skipping")
                    skipped_count += 1
                    continue
                
                # Encrypt tokens
                encrypted_access = encryption.encrypt(access_token) if access_token else None
                encrypted_refresh = encryption.encrypt(refresh_token) if refresh_token else None
                
                # Update database
                db.execute(text("""
                    UPDATE sessions 
                    SET gmail_access_token = :access_token,
                        gmail_refresh_token = :refresh_token
                    WHERE id = :session_id
                """), {
                    'access_token': encrypted_access,
                    'refresh_token': encrypted_refresh,
                    'session_id': session_id
                })
                
                encrypted_count += 1
                
                if encrypted_count % 10 == 0:
                    logger.info(f"Progress: {encrypted_count}/{total} sessions encrypted")
                
            except Exception as e:
                logger.error(f"Failed to encrypt tokens for session {session_id}: {e}")
                error_count += 1
                continue
        
        # Commit changes
        db.commit()
        
        logger.info("=" * 60)
        logger.info(f"✅ Migration complete!")
        logger.info(f"   Encrypted: {encrypted_count}")
        logger.info(f"   Skipped (already encrypted): {skipped_count}")
        logger.info(f"   Errors: {error_count}")
        logger.info(f"   Total: {total}")
        logger.info("=" * 60)
        
        if error_count > 0:
            logger.warning(f"⚠️  {error_count} sessions had errors and were not encrypted")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    
    finally:
        db.close()


def test_encryption():
    """Test encryption/decryption to verify it's working"""
    try:
        encryption = TokenEncryption()
        
        test_token = "test-access-token-abc123"
        encrypted = encryption.encrypt(test_token)
        decrypted = encryption.decrypt(encrypted)
        
        if decrypted == test_token:
            logger.info("[OK] Encryption test passed")
            return True
        else:
            logger.error("[ERROR] Encryption test failed - decrypted value doesn't match")
            return False
    except Exception as e:
        logger.error(f"[ERROR] Encryption test failed: {e}")
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Gmail Token Encryption Migration")
    print("=" * 60)
    print()
    print("⚠️  WARNING: Make sure you have backed up your database!")
    print()
    print("This script will:")
    print("  1. Connect to your database")
    print("  2. Find all sessions with Gmail tokens")
    print("  3. Encrypt the tokens using Fernet encryption")
    print("  4. Update the database")
    print()
    print("Requirements:")
    print("  - ENCRYPTION_KEY environment variable set")
    print("  - DATABASE_URL environment variable set")
    print("  - Database backup completed")
    print()
    
    # Test encryption first
    print("Testing encryption...")
    if not test_encryption():
        print("\n❌ Encryption test failed. Aborting.")
        sys.exit(1)
    
    print()
    
    # Run migration
    encrypt_existing_tokens()
