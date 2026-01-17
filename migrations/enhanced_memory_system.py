"""
Database Migration: Enhanced Memory System Tables

Creates tables for the enhanced memory system:
- memory_nodes: Store memory graph nodes (queries, intents, tools, execution chains)
- memory_edges: Store relationships between nodes
- user_preferences: Store learned user preferences and patterns
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from src.database.database import get_engine, _get_database_url
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def upgrade():
    """Create enhanced memory system tables"""
    engine = get_engine()
    database_url = _get_database_url()
    is_sqlite = database_url.startswith('sqlite')
    
    try:
        with engine.begin() as connection:
            logger.info("Creating enhanced memory system tables...")
            
            # Determine column types based on database type
            if is_sqlite:
                json_type = "TEXT"
                datetime_type = "DATETIME"
                now_func = "datetime('now')"
            else:
                json_type = "JSON"
                datetime_type = "TIMESTAMP"
                now_func = "NOW()"
            
            # Create memory_nodes table
            connection.execute(text(f"""
                CREATE TABLE IF NOT EXISTS memory_nodes (
                    id VARCHAR PRIMARY KEY,
                    node_type VARCHAR NOT NULL,
                    user_id INTEGER,
                    data {json_type} NOT NULL DEFAULT '{{}}'::text,
                    confidence FLOAT NOT NULL DEFAULT 1.0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_used {datetime_type},
                    created_at {datetime_type} NOT NULL DEFAULT {now_func},
                    updated_at {datetime_type} NOT NULL DEFAULT {now_func}
                )
            """))
            
            # Create indexes for memory_nodes
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_nodes_node_type ON memory_nodes(node_type)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_nodes_user_id ON memory_nodes(user_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_nodes_last_used ON memory_nodes(last_used)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_nodes_confidence ON memory_nodes(confidence)"))
            
            # Create memory_edges table
            connection.execute(text(f"""
                CREATE TABLE IF NOT EXISTS memory_edges (
                    id VARCHAR PRIMARY KEY,
                    source_id VARCHAR NOT NULL,
                    target_id VARCHAR NOT NULL,
                    relationship_type VARCHAR NOT NULL,
                    weight FLOAT NOT NULL DEFAULT 1.0,
                    confidence FLOAT NOT NULL DEFAULT 1.0,
                    data {json_type} DEFAULT '{{}}'::text,
                    created_at {datetime_type} NOT NULL DEFAULT {now_func},
                    updated_at {datetime_type} NOT NULL DEFAULT {now_func}
                )
            """))
            
            # Create indexes for memory_edges
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_edges_source_id ON memory_edges(source_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_edges_target_id ON memory_edges(target_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_edges_relationship_type ON memory_edges(relationship_type)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_edges_weight ON memory_edges(weight)"))
            
            # Create user_preferences table
            connection.execute(text(f"""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id VARCHAR PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    pattern_type VARCHAR NOT NULL,
                    pattern_data {json_type} NOT NULL,
                    success_rate FLOAT NOT NULL DEFAULT 0.0,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    confidence FLOAT NOT NULL DEFAULT 0.5,
                    last_used {datetime_type} NOT NULL DEFAULT {now_func},
                    created_at {datetime_type} NOT NULL DEFAULT {now_func},
                    updated_at {datetime_type} NOT NULL DEFAULT {now_func}
                )
            """))
            
            # Create indexes for user_preferences
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_user_preferences_user_id ON user_preferences(user_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_user_preferences_pattern_type ON user_preferences(pattern_type)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_user_preferences_success_rate ON user_preferences(success_rate)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_user_preferences_last_used ON user_preferences(last_used)"))
            
            # Create execution_analytics table
            connection.execute(text(f"""
                CREATE TABLE IF NOT EXISTS execution_analytics (
                    id VARCHAR PRIMARY KEY,
                    user_id INTEGER,
                    query TEXT NOT NULL,
                    execution_type VARCHAR NOT NULL,
                    tools_used {json_type},
                    execution_time FLOAT NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    context_enrichments INTEGER NOT NULL DEFAULT 0,
                    memory_hits INTEGER NOT NULL DEFAULT 0,
                    parallel_executions INTEGER NOT NULL DEFAULT 0,
                    created_at {datetime_type} NOT NULL DEFAULT {now_func}
                )
            """))
            
            # Create indexes for execution_analytics
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_analytics_user_id ON execution_analytics(user_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_analytics_execution_type ON execution_analytics(execution_type)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_analytics_success ON execution_analytics(success)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_analytics_execution_time ON execution_analytics(execution_time)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_analytics_created_at ON execution_analytics(created_at)"))
            
            logger.info("Enhanced memory system tables created successfully!")
            
    except Exception as e:
        logger.error(f"Failed to create enhanced memory system tables: {e}")
        raise


def downgrade():
    """Drop enhanced memory system tables"""
    engine = get_engine()
    
    try:
        with engine.begin() as connection:
            logger.info("Dropping enhanced memory system tables...")
            
            # Drop tables in reverse order
            connection.execute(text("DROP TABLE IF EXISTS execution_analytics"))
            connection.execute(text("DROP TABLE IF EXISTS user_preferences"))
            connection.execute(text("DROP TABLE IF EXISTS memory_edges"))
            connection.execute(text("DROP TABLE IF EXISTS memory_nodes"))
            
            logger.info("Enhanced memory system tables dropped successfully!")
            
    except Exception as e:
        logger.error(f"Failed to drop enhanced memory system tables: {e}")
        raise


if __name__ == "__main__":
    upgrade()
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('relationship_type', sa.String(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False, default=1.0),
        sa.Column('confidence', sa.Float(), nullable=False, default=1.0),
        sa.Column('data', postgresql.JSON(astext_type=sa.Text()), nullable=True, default={}),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['source_id'], ['memory_nodes.id'], ),
        sa.ForeignKeyConstraint(['target_id'], ['memory_nodes.id'], ),
    )
    
    # Create indexes for memory_edges
    op.create_index('ix_memory_edges_source_id', 'memory_edges', ['source_id'])
    op.create_index('ix_memory_edges_target_id', 'memory_edges', ['target_id'])
    op.create_index('ix_memory_edges_relationship_type', 'memory_edges', ['relationship_type'])
    op.create_index('ix_memory_edges_weight', 'memory_edges', ['weight'])
    
    # Create user_preferences table for learned patterns
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('pattern_type', sa.String(), nullable=False),  # 'query_pattern', 'tool_preference', etc.
        sa.Column('pattern_data', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('success_rate', sa.Float(), nullable=False, default=0.0),
        sa.Column('usage_count', sa.Integer(), nullable=False, default=0),
        sa.Column('confidence', sa.Float(), nullable=False, default=0.5),
        sa.Column('last_used', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create indexes for user_preferences
    op.create_index('ix_user_preferences_user_id', 'user_preferences', ['user_id'])
    op.create_index('ix_user_preferences_pattern_type', 'user_preferences', ['pattern_type'])
    op.create_index('ix_user_preferences_success_rate', 'user_preferences', ['success_rate'])
    op.create_index('ix_user_preferences_last_used', 'user_preferences', ['last_used'])
    
    # Create execution_analytics table for performance tracking
    op.create_table(
        'execution_analytics',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('execution_type', sa.String(), nullable=False),  # 'single_step', 'multi_step', 'enhanced'
        sa.Column('tools_used', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('execution_time', sa.Float(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('context_enrichments', sa.Integer(), nullable=False, default=0),
        sa.Column('memory_hits', sa.Integer(), nullable=False, default=0),
        sa.Column('parallel_executions', sa.Integer(), nullable=False, default=0),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
    )
    
    # Create indexes for execution_analytics
    op.create_index('ix_execution_analytics_user_id', 'execution_analytics', ['user_id'])
    op.create_index('ix_execution_analytics_execution_type', 'execution_analytics', ['execution_type'])
    op.create_index('ix_execution_analytics_success', 'execution_analytics', ['success'])
    op.create_index('ix_execution_analytics_created_at', 'execution_analytics', ['created_at'])
    op.create_index('ix_execution_analytics_execution_time', 'execution_analytics', ['execution_time'])


def downgrade():
    """Drop enhanced memory system tables"""
    
    # Drop indexes first
    op.drop_index('ix_execution_analytics_execution_time', 'execution_analytics')
    op.drop_index('ix_execution_analytics_created_at', 'execution_analytics')
    op.drop_index('ix_execution_analytics_success', 'execution_analytics')
    op.drop_index('ix_execution_analytics_execution_type', 'execution_analytics')
    op.drop_index('ix_execution_analytics_user_id', 'execution_analytics')
    
    op.drop_index('ix_user_preferences_last_used', 'user_preferences')
    op.drop_index('ix_user_preferences_success_rate', 'user_preferences')
    op.drop_index('ix_user_preferences_pattern_type', 'user_preferences')
    op.drop_index('ix_user_preferences_user_id', 'user_preferences')
    
    op.drop_index('ix_memory_edges_weight', 'memory_edges')
    op.drop_index('ix_memory_edges_relationship_type', 'memory_edges')
    op.drop_index('ix_memory_edges_target_id', 'memory_edges')
    op.drop_index('ix_memory_edges_source_id', 'memory_edges')
    
    op.drop_index('ix_memory_nodes_confidence', 'memory_nodes')
    op.drop_index('ix_memory_nodes_last_used', 'memory_nodes')
    op.drop_index('ix_memory_nodes_user_id', 'memory_nodes')
    op.drop_index('ix_memory_nodes_node_type', 'memory_nodes')
    
    # Drop tables
    op.drop_table('execution_analytics')
    op.drop_table('user_preferences')
    op.drop_table('memory_edges')
    op.drop_table('memory_nodes')
