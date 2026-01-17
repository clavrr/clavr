"""
Add Capabilities Persistence Tables

Migration to add tables for capabilities module persistence:
- user_capability_preferences
- execution_patterns
- pattern_clusters
- user_behavior_profiles
- baseline_metrics
- detected_anomalies

Run with: python -m migrations.add_capabilities_tables
"""

import asyncio
from sqlalchemy import text
from src.database.async_database import get_async_engine
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def migrate():
    """Run the capabilities tables migration"""
    
    engine = get_async_engine()
    
    async with engine.begin() as conn:
        # Check which tables already exist
        result = await conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """))
        existing_tables = {row[0] for row in result.fetchall()}
        
        logger.info(f"Existing tables: {existing_tables}")
        
        # 1. Create user_capability_preferences table
        if 'user_capability_preferences' not in existing_tables:
            logger.info("Creating user_capability_preferences table...")
            await conn.execute(text("""
                CREATE TABLE user_capability_preferences (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    preferred_format VARCHAR(50) DEFAULT 'conversational',
                    preferred_detail_level VARCHAR(50) DEFAULT 'standard',
                    include_timestamps BOOLEAN DEFAULT FALSE,
                    include_statistics BOOLEAN DEFAULT FALSE,
                    use_emojis BOOLEAN DEFAULT FALSE,
                    use_markdown BOOLEAN DEFAULT TRUE,
                    preferred_language VARCHAR(10) DEFAULT 'en',
                    max_items_shown INTEGER DEFAULT 10,
                    group_by_domain BOOLEAN DEFAULT TRUE,
                    show_alternatives BOOLEAN DEFAULT TRUE,
                    include_actions BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_user_cap_prefs_user_id ON user_capability_preferences(user_id)
            """))
            logger.info("✅ Created user_capability_preferences table")
        
        # 2. Create execution_patterns table
        if 'execution_patterns' not in existing_tables:
            logger.info("Creating execution_patterns table...")
            await conn.execute(text("""
                CREATE TABLE execution_patterns (
                    id SERIAL PRIMARY KEY,
                    signature VARCHAR(255) NOT NULL,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    sequence_data JSONB NOT NULL,
                    total_duration_ms FLOAT DEFAULT 0.0,
                    success BOOLEAN DEFAULT TRUE,
                    occurrence_count INTEGER DEFAULT 1,
                    avg_duration_ms FLOAT DEFAULT 0.0,
                    success_rate FLOAT DEFAULT 1.0,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_exec_patterns_signature ON execution_patterns(signature)
            """))
            await conn.execute(text("""
                CREATE INDEX idx_exec_patterns_user ON execution_patterns(user_id)
            """))
            await conn.execute(text("""
                CREATE INDEX idx_exec_patterns_last_seen ON execution_patterns(last_seen_at)
            """))
            logger.info("✅ Created execution_patterns table")
        
        # 3. Create pattern_clusters table
        if 'pattern_clusters' not in existing_tables:
            logger.info("Creating pattern_clusters table...")
            await conn.execute(text("""
                CREATE TABLE pattern_clusters (
                    id SERIAL PRIMARY KEY,
                    cluster_id VARCHAR(100) UNIQUE NOT NULL,
                    pattern_name VARCHAR(255) NOT NULL,
                    centroid_data JSONB NOT NULL,
                    characteristics JSONB DEFAULT '{}',
                    member_count INTEGER DEFAULT 1,
                    confidence FLOAT DEFAULT 0.7,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_pattern_clusters_confidence ON pattern_clusters(confidence)
            """))
            logger.info("✅ Created pattern_clusters table")
        
        # 4. Create user_behavior_profiles table
        if 'user_behavior_profiles' not in existing_tables:
            logger.info("Creating user_behavior_profiles table...")
            await conn.execute(text("""
                CREATE TABLE user_behavior_profiles (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    pattern_preferences JSONB DEFAULT '{}',
                    total_patterns INTEGER DEFAULT 0,
                    success_rate FLOAT DEFAULT 0.0,
                    avg_execution_time FLOAT DEFAULT 0.0,
                    preferred_domains JSONB DEFAULT '{}',
                    preferred_intents JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_user_behavior_user_id ON user_behavior_profiles(user_id)
            """))
            logger.info("✅ Created user_behavior_profiles table")
        
        # 5. Create baseline_metrics table
        if 'baseline_metrics' not in existing_tables:
            logger.info("Creating baseline_metrics table...")
            await conn.execute(text("""
                CREATE TABLE baseline_metrics (
                    id SERIAL PRIMARY KEY,
                    pattern_signature VARCHAR(500) UNIQUE NOT NULL,
                    avg_duration FLOAT DEFAULT 0.0,
                    min_duration FLOAT DEFAULT 0.0,
                    max_duration FLOAT DEFAULT 0.0,
                    success_rate FLOAT DEFAULT 1.0,
                    sample_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_baseline_pattern_sig ON baseline_metrics(pattern_signature)
            """))
            logger.info("✅ Created baseline_metrics table")
        
        # 6. Create detected_anomalies table
        if 'detected_anomalies' not in existing_tables:
            logger.info("Creating detected_anomalies table...")
            await conn.execute(text("""
                CREATE TABLE detected_anomalies (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    anomaly_type VARCHAR(50) NOT NULL,
                    severity VARCHAR(20) NOT NULL,
                    description TEXT NOT NULL,
                    affected_patterns JSONB DEFAULT '[]',
                    confidence FLOAT DEFAULT 0.0,
                    suggested_action TEXT,
                    acknowledged BOOLEAN DEFAULT FALSE,
                    resolved BOOLEAN DEFAULT FALSE,
                    resolved_at TIMESTAMP,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE INDEX idx_anomalies_user ON detected_anomalies(user_id)
            """))
            await conn.execute(text("""
                CREATE INDEX idx_anomalies_type_severity ON detected_anomalies(anomaly_type, severity)
            """))
            await conn.execute(text("""
                CREATE INDEX idx_anomalies_unresolved ON detected_anomalies(resolved, detected_at)
            """))
            logger.info("✅ Created detected_anomalies table")
        
        logger.info("✅ Capabilities tables migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
