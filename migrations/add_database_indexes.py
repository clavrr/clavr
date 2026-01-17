#!/usr/bin/env python3
"""
Database Index Migration Script
Adds performance-optimizing indexes to existing tables

Run this script to add indexes without recreating tables:
    python migrations/add_database_indexes.py

This is safe to run multiple times (idempotent).
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine, text, inspect
from src.database.database import get_engine, DATABASE_URL
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def index_exists(engine, table_name: str, index_name: str) -> bool:
    """Check if an index already exists"""
    inspector = inspect(engine)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def add_indexes_sqlite(engine):
    """Add indexes for SQLite database"""
    indexes_to_create = [
        # User table indexes
        ("CREATE INDEX IF NOT EXISTS idx_users_email_indexed ON users (email_indexed);",
         "users", "idx_users_email_indexed"),
        
        ("CREATE INDEX IF NOT EXISTS idx_users_indexing_status ON users (indexing_status);",
         "users", "idx_users_indexing_status"),
        
        ("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at);",
         "users", "idx_users_created_at"),
        
        ("CREATE INDEX IF NOT EXISTS idx_users_last_email_synced ON users (last_email_synced_at);",
         "users", "idx_users_last_email_synced"),
        
        # Session table indexes
        ("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);",
         "sessions", "idx_sessions_expires_at"),
        
        ("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at);",
         "sessions", "idx_sessions_created_at"),
        
        ("CREATE INDEX IF NOT EXISTS idx_sessions_user_expires ON sessions (user_id, expires_at);",
         "sessions", "idx_sessions_user_expires"),
        
        # UserSettings table index
        ("CREATE INDEX IF NOT EXISTS idx_user_settings_created_at ON user_settings (created_at);",
         "user_settings", "idx_user_settings_created_at"),
    ]
    
    with engine.begin() as conn:
        for sql, table, index_name in indexes_to_create:
            if not index_exists(engine, table, index_name):
                try:
                    conn.execute(text(sql))
                    print(f"✅ Created index: {index_name} on {table}")
                    logger.info(f"✅ Created index: {index_name} on {table}")
                except Exception as e:
                    print(f"⚠️  Could not create index {index_name}: {e}")
                    logger.warning(f"⚠️  Could not create index {index_name}: {e}")
            else:
                print(f"⏭️  Index already exists: {index_name}")
                logger.debug(f"⏭️  Index already exists: {index_name}")


def add_indexes_postgres(engine):
    """Add indexes for PostgreSQL database"""
    indexes_to_create = [
        # User table indexes
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email_indexed ON users (email_indexed);",
         "users", "idx_users_email_indexed"),
        
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_indexing_status ON users (indexing_status);",
         "users", "idx_users_indexing_status"),
        
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_created_at ON users (created_at DESC);",
         "users", "idx_users_created_at"),
        
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_last_email_synced ON users (last_email_synced_at DESC) WHERE last_email_synced_at IS NOT NULL;",
         "users", "idx_users_last_email_synced"),
        
        # Session table indexes
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);",
         "sessions", "idx_sessions_expires_at"),
        
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC);",
         "sessions", "idx_sessions_created_at"),
        
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_user_expires ON sessions (user_id, expires_at);",
         "sessions", "idx_sessions_user_expires"),
        
        # UserSettings table index
        ("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_settings_created_at ON user_settings (created_at DESC);",
         "user_settings", "idx_user_settings_created_at"),
    ]
    
    # PostgreSQL requires autocommit for CONCURRENTLY
    conn = engine.connect()
    conn.execution_options(isolation_level="AUTOCOMMIT")
    
    try:
        for sql, table, index_name in indexes_to_create:
            if not index_exists(engine, table, index_name):
                try:
                    conn.execute(text(sql))
                    print(f"✅ Created index: {index_name} on {table}")
                    logger.info(f"✅ Created index: {index_name} on {table}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"⏭️  Index already exists: {index_name}")
                        logger.debug(f"⏭️  Index already exists: {index_name}")
                    else:
                        print(f"⚠️  Could not create index {index_name}: {e}")
                        logger.warning(f"⚠️  Could not create index {index_name}: {e}")
            else:
                print(f"⏭️  Index already exists: {index_name}")
                logger.debug(f"⏭️  Index already exists: {index_name}")
    finally:
        conn.close()


def main():
    """Main migration function"""
    print("=" * 80)
    print("DATABASE INDEX MIGRATION")
    print("=" * 80)
    print(f"Database URL: {DATABASE_URL[:20]}...")
    logger.info("=" * 80)
    logger.info("DATABASE INDEX MIGRATION")
    logger.info("=" * 80)
    logger.info(f"Database URL: {DATABASE_URL[:20]}...")
    
    engine = get_engine()
    
    try:
        if DATABASE_URL.startswith('sqlite'):
            print("Detected SQLite database")
            logger.info("Detected SQLite database")
            add_indexes_sqlite(engine)
        elif DATABASE_URL.startswith('postgresql'):
            print("Detected PostgreSQL database")
            logger.info("Detected PostgreSQL database")
            add_indexes_postgres(engine)
        else:
            print(f"Unsupported database type: {DATABASE_URL}")
            logger.error(f"Unsupported database type: {DATABASE_URL}")
            return 1
        
        print("=" * 80)
        print("✅ INDEX MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 80)
        logger.info("=" * 80)
        logger.info("✅ INDEX MIGRATION COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        return 0
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
