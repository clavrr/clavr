"""fix_entities_column_type

Revision ID: e8f9a0b1c2d3
Revises: dc552d6d1e48
Create Date: 2026-01-17 04:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e8f9a0b1c2d3'
down_revision = 'dc552d6d1e48'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Change entities column from JSON to Text to support EncryptedJSON (which stores encrypted base64 strings)
    # We cast existing JSON data to text.
    # The application side EncryptedJSON type handles fallback to plaintext JSON if decryption fails,
    # so existing data remains accessible.
    op.alter_column('conversation_messages', 'entities',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=sa.Text(),
               existing_nullable=True,
               postgresql_using='entities::text')


def downgrade() -> None:
    # Revert entities column to JSON.
    # Warning: This will fail if the column contains non-JSON data (e.g. encrypted strings).
    # This downgrade is only safe if you've decrypted all data or deleted it.
    op.alter_column('conversation_messages', 'entities',
               existing_type=sa.Text(),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True,
               postgresql_using='entities::json')
