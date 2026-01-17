"""
Database Migration: Add Interaction Sessions Table

Stores Gemini Interactions API session IDs for stateful conversations.
Enables multi-turn conversations to survive server restarts.

Revision ID: add_interaction_sessions
Create Date: 2025-12-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_interaction_sessions'
down_revision = 'add_oauth_states_table'  # Previous migration
branch_labels = None
depends_on = None


def upgrade():
    """Create interaction_sessions table for persistent stateful conversations."""
    
    # Create interaction_sessions table
    op.create_table(
        'interaction_sessions',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('interaction_id', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # Create index on updated_at for cleanup queries
    op.create_index('ix_interaction_sessions_updated_at', 'interaction_sessions', ['updated_at'])
    
    print("✅ Interaction sessions table created successfully")
    print("   - Persists Gemini Interactions API session IDs")
    print("   - Survives server restarts")
    print("   - Works with multiple workers")


def downgrade():
    """Remove interaction_sessions table."""
    
    # Drop indexes
    op.drop_index('ix_interaction_sessions_updated_at', table_name='interaction_sessions')
    
    # Drop table
    op.drop_table('interaction_sessions')
    
    print("✅ Interaction sessions table removed")
