"""Add granted_scopes to sessions table

Revision ID: 234d4b6aef5f
Revises: add_is_active_to_integrations
Create Date: 2026-01-06 12:53:50.457327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '234d4b6aef5f'
down_revision: Union[str, None] = 'add_is_active_to_integrations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add granted_scopes column to sessions table
    # This stores the OAuth scopes granted by the user (comma-separated)
    op.add_column('sessions', sa.Column('granted_scopes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'granted_scopes')
