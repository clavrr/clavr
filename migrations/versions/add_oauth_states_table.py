"""
Database Migration: Add OAuth States Table for CSRF Protection

Revision ID: add_oauth_states_table
Create Date: 2025-11-17
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = 'add_oauth_states_table'
down_revision = 'add_smart_indexing_fields'  # Previous migration
branch_labels = None
depends_on = None


def upgrade():
    """Create oauth_states table for database-backed CSRF protection."""
    
    # Create oauth_states table
    op.create_table(
        'oauth_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for performance
    op.create_index('ix_oauth_states_id', 'oauth_states', ['id'])
    op.create_index('ix_oauth_states_state', 'oauth_states', ['state'], unique=True)
    op.create_index('ix_oauth_states_created_at', 'oauth_states', ['created_at'])
    op.create_index('ix_oauth_states_expires_at', 'oauth_states', ['expires_at'])
    op.create_index('ix_oauth_states_used', 'oauth_states', ['used'])
    
    # Composite index for efficient OAuth state validation
    op.create_index(
        'idx_oauth_state_validity',
        'oauth_states',
        ['state', 'used', 'expires_at']
    )
    
    print("✅ OAuth states table created successfully")
    print("   - Provides database-backed CSRF protection for OAuth flow")
    print("   - Survives server restarts")
    print("   - Works with multiple workers")


def downgrade():
    """Remove oauth_states table."""
    
    # Drop indexes
    op.drop_index('idx_oauth_state_validity', table_name='oauth_states')
    op.drop_index('ix_oauth_states_used', table_name='oauth_states')
    op.drop_index('ix_oauth_states_expires_at', table_name='oauth_states')
    op.drop_index('ix_oauth_states_created_at', table_name='oauth_states')
    op.drop_index('ix_oauth_states_state', table_name='oauth_states')
    op.drop_index('ix_oauth_states_id', table_name='oauth_states')
    
    # Drop table
    op.drop_table('oauth_states')
    
    print("✅ OAuth states table removed")
