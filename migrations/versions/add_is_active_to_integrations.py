"""
Database Migration: Add is_active field to user_integrations

Revision ID: add_is_active_to_integrations
Create Date: 2025-12-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_is_active_to_integrations'
down_revision = 'f5c376e1f726'  # Chain after add_agent_facts_table
branch_labels = None
depends_on = None


def upgrade():
    """Add is_active field to user_integrations for soft disconnect."""
    
    # Add is_active column with default True
    op.add_column(
        'user_integrations', 
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False)
    )
    
    # Create index for performance (filtering by active status)
    op.create_index('idx_user_integrations_is_active', 'user_integrations', ['is_active'])
    
    print("✅ is_active field added to user_integrations")


def downgrade():
    """Remove is_active field."""
    
    # Drop index
    op.drop_index('idx_user_integrations_is_active', table_name='user_integrations')
    
    # Drop column
    op.drop_column('user_integrations', 'is_active')
    
    print("✅ is_active field removed from user_integrations")
