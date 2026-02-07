"""merge_classification_migration

Revision ID: e09c3cf16eae
Revises: a1b2c3d4e5f6, b2c3d4e5f6a7
Create Date: 2026-02-04 22:54:51.613155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e09c3cf16eae'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'b2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
