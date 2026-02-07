"""Add message_classifications table for LLM-based classification

Revision ID: a1b2c3d4e5f6
Revises: dc552d6d1e48
Create Date: 2026-02-04
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'a1b2c3d4e5f6'
down_revision = 'dc552d6d1e48'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'message_classifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_id', sa.String(255), nullable=False),
        sa.Column('needs_response', sa.Boolean(), nullable=False, default=False),
        sa.Column('urgency', sa.String(20), default='low'),
        sa.Column('classification_reason', sa.Text()),  # EncryptedString in model
        sa.Column('suggested_action', sa.String(50)),
        sa.Column('title', sa.Text(), nullable=False),  # EncryptedString
        sa.Column('sender', sa.Text()),  # EncryptedString
        sa.Column('snippet', sa.Text()),  # EncryptedString
        sa.Column('source_date', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('classified_at', sa.DateTime(), nullable=False),
        sa.Column('is_dismissed', sa.Boolean(), default=False),
        sa.Column('dismissed_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_message_classifications_id', 'message_classifications', ['id'])
    op.create_index('ix_message_classifications_user_id', 'message_classifications', ['user_id'])
    op.create_index('ix_message_classifications_source_type', 'message_classifications', ['source_type'])
    op.create_index('ix_message_classifications_source_id', 'message_classifications', ['source_id'])
    op.create_index('ix_message_classifications_needs_response', 'message_classifications', ['needs_response'])
    op.create_index('ix_message_classifications_urgency', 'message_classifications', ['urgency'])
    op.create_index('ix_message_classifications_classified_at', 'message_classifications', ['classified_at'])
    op.create_index('ix_message_classifications_is_dismissed', 'message_classifications', ['is_dismissed'])
    
    # Composite indexes for common queries
    op.create_index(
        'idx_classification_user_needs_response',
        'message_classifications',
        ['user_id', 'needs_response', 'classified_at']
    )
    op.create_index(
        'idx_classification_source',
        'message_classifications',
        ['user_id', 'source_type', 'source_id'],
        unique=True
    )


def downgrade():
    op.drop_index('idx_classification_source', 'message_classifications')
    op.drop_index('idx_classification_user_needs_response', 'message_classifications')
    op.drop_index('ix_message_classifications_is_dismissed', 'message_classifications')
    op.drop_index('ix_message_classifications_classified_at', 'message_classifications')
    op.drop_index('ix_message_classifications_urgency', 'message_classifications')
    op.drop_index('ix_message_classifications_needs_response', 'message_classifications')
    op.drop_index('ix_message_classifications_source_id', 'message_classifications')
    op.drop_index('ix_message_classifications_source_type', 'message_classifications')
    op.drop_index('ix_message_classifications_user_id', 'message_classifications')
    op.drop_index('ix_message_classifications_id', 'message_classifications')
    op.drop_table('message_classifications')
