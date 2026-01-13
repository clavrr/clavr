"""
Migration Script: Hash Existing Session Tokens
================================================

This script migrates existing plaintext session tokens to hashed tokens.

WARNING: This is a ONE-WAY migration. After running this:
1. All existing sessions will be invalidated
2. Users will need to log in again
3. Raw tokens cannot be recovered

Alternative Approach:
- Instead of migrating, you can simply delete all existing sessions
- Users will be logged out and need to authenticate again
- New sessions will use hashed tokens automatically

Usage:
    python -m scripts.migrate_session_tokens
    
    Or to just clear all sessions:
    python -m scripts.migrate_session_tokens --clear-only
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import get_db
from src.database.models import Session
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def clear_all_sessions():
    """
    Clear all existing sessions (recommended approach)
    
    This is simpler and safer than trying to migrate plaintext tokens.
    Users will need to log in again, which generates new hashed tokens.
    """
    db = next(get_db())
    try:
        count = db.query(Session).count()
        logger.info(f"Found {count} existing sessions")
        
        if count == 0:
            logger.info("No sessions to clear")
            return
        
        # Confirm deletion
        response = input(f"\n⚠️  This will delete {count} sessions. Users will need to log in again. Continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logger.info("Migration cancelled")
            return
        
        # Delete all sessions
        db.query(Session).delete()
        db.commit()
        
        logger.info(f"✅ Successfully cleared {count} sessions")
        logger.info("All users will need to log in again with the new hashed token system")
        
    except Exception as e:
        logger.error(f"Failed to clear sessions: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


def migrate_with_warning():
    """
    Attempt to migrate tokens (NOT RECOMMENDED)
    
    This is impossible since we can't recover the original tokens from the database.
    We can only clear and regenerate.
    """
    logger.error("❌ Cannot migrate plaintext tokens to hashed tokens")
    logger.error("   Reason: The original tokens were stored in plaintext")
    logger.error("   Solution: Clear all sessions and have users log in again")
    logger.info("")
    logger.info("Recommended approach:")
    logger.info("  python -m scripts.migrate_session_tokens --clear-only")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Migrate session tokens to hashed format")
    parser.add_argument(
        '--clear-only',
        action='store_true',
        help='Clear all existing sessions (recommended)'
    )
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("Session Token Migration Script")
    logger.info("=" * 70)
    logger.info("")
    
    if args.clear_only:
        clear_all_sessions()
    else:
        logger.info("⚠️  NOTE: You must use --clear-only flag")
        logger.info("")
        logger.info("Migration is impossible because:")
        logger.info("  1. Existing tokens are stored as plaintext")
        logger.info("  2. We need to hash them, but clients already have the raw tokens")
        logger.info("  3. There's no way to match old raw tokens with new hashes")
        logger.info("")
        logger.info("Solution: Clear all sessions and have users log in again")
        logger.info("")
        logger.info("Run with: python -m scripts.migrate_session_tokens --clear-only")
        sys.exit(1)


if __name__ == "__main__":
    main()
