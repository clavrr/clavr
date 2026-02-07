"""fix_interaction_context

Revision ID: b2c3d4e5f6a7
Revises: e8f9a0b1c2d3
Create Date: 2026-01-17 04:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Fix interaction_sessions.session_context (JSON -> Text)
    # The migration that added it (dc552d6d1e48) used sa.JSON(), but model uses EncryptedJSON (Text).
    # We cast existing JSON data to text to preserve it.
    op.alter_column('interaction_sessions', 'session_context',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=sa.Text(),
               existing_nullable=True,
               postgresql_using='session_context::text')

    # 2. Check and fix user_writing_profiles.profile_data if it exists and is JSON
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_writing_profiles' in inspector.get_table_names():
        columns = {c['name']: c for c in inspector.get_columns('user_writing_profiles')}
        if 'profile_data' in columns:
            col_type = columns['profile_data']['type']
            # Check if it's JSON type (PostgreSQL JSON or JSONB)
            is_json = isinstance(col_type, (postgresql.JSON, postgresql.JSONB)) or str(col_type).upper().startswith('JSON')
            
            if is_json:
                print("Fixing user_writing_profiles.profile_data column type...")
                op.alter_column('user_writing_profiles', 'profile_data',
                           existing_type=postgresql.JSON(astext_type=sa.Text()),
                           type_=sa.Text(),
                           existing_nullable=False,
                           postgresql_using='profile_data::text')

def downgrade() -> None:
    # Revert interaction_sessions.session_context to JSON
    # This might fail if the text is not valid plaintext JSON
    op.alter_column('interaction_sessions', 'session_context',
               existing_type=sa.Text(),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True,
               postgresql_using='session_context::json')
