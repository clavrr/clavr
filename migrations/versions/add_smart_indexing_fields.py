"""
Database Migration: Add Smart Indexing Fields

Revision ID: add_smart_indexing_fields
Create Date: 2025-11-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_smart_indexing_fields'
down_revision = None  # Update this with your latest migration ID
branch_labels = None
depends_on = None


def upgrade():
    """Add smart indexing fields to users table."""
    
    # Add new columns
    op.add_column('users', sa.Column('last_indexed_timestamp', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('initial_indexing_complete', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('indexing_date_range_start', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('total_emails_indexed', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('indexing_progress_percent', sa.Float(), server_default='0.0', nullable=False))
    
    # Create indexes for performance
    op.create_index('idx_users_last_indexed', 'users', ['last_indexed_timestamp'])
    op.create_index('idx_users_initial_complete', 'users', ['initial_indexing_complete'])
    
    print("✅ Smart indexing fields added successfully")


def downgrade():
    """Remove smart indexing fields."""
    
    # Drop indexes
    op.drop_index('idx_users_initial_complete', table_name='users')
    op.drop_index('idx_users_last_indexed', table_name='users')
    
    # Drop columns
    op.drop_column('users', 'indexing_progress_percent')
    op.drop_column('users', 'total_emails_indexed')
    op.drop_column('users', 'indexing_date_range_start')
    op.drop_column('users', 'initial_indexing_complete')
    op.drop_column('users', 'last_indexed_timestamp')
    
    print("✅ Smart indexing fields removed")
