"""merge_migration_heads

Revision ID: 4e38256c6116
Revises: add_interaction_sessions, dc2494b491ca
Create Date: 2025-12-15 14:12:23.629025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e38256c6116'
down_revision: Union[str, None] = ('add_interaction_sessions', 'dc2494b491ca')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
