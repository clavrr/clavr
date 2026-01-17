"""Add Ghost, Proactive, and Notification models

Revision ID: dc552d6d1e48
Revises: 234d4b6aef5f
Create Date: 2026-01-16 14:21:18.845337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'dc552d6d1e48'
down_revision: Union[str, None] = '234d4b6aef5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tables IF NOT EXISTS (to handle environments where init_db was already called)
    
    # helper to check if table exists
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # Ghost Drafts
    if 'ghost_drafts' not in existing_tables:
        op.create_table('ghost_drafts',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('source_channel', sa.String(length=100), nullable=True),
            sa.Column('source_thread_ts', sa.String(length=100), nullable=True),
            sa.Column('integration_type', sa.String(length=50), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('resolved_entity_id', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_ghost_drafts_created_at'), 'ghost_drafts', ['created_at'], unique=False)
        op.create_index(op.f('ix_ghost_drafts_id'), 'ghost_drafts', ['id'], unique=False)
        op.create_index(op.f('ix_ghost_drafts_source_thread_ts'), 'ghost_drafts', ['source_thread_ts'], unique=False)
        op.create_index(op.f('ix_ghost_drafts_status'), 'ghost_drafts', ['status'], unique=False)
        op.create_index(op.f('ix_ghost_drafts_user_id'), 'ghost_drafts', ['user_id'], unique=False)

    # In App Notifications
    if 'in_app_notifications' not in existing_tables:
        op.create_table('in_app_notifications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('notification_type', sa.String(length=50), nullable=False),
            sa.Column('priority', sa.String(length=20), nullable=True),
            sa.Column('icon', sa.String(length=50), nullable=True),
            sa.Column('action_url', sa.String(length=500), nullable=True),
            sa.Column('action_label', sa.String(length=100), nullable=True),
            sa.Column('related_action_id', sa.Integer(), nullable=True),
            sa.Column('is_read', sa.Boolean(), nullable=True),
            sa.Column('is_dismissed', sa.Boolean(), nullable=True),
            sa.Column('read_at', sa.DateTime(), nullable=True),
            sa.Column('dismissed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_notification_type', 'in_app_notifications', ['user_id', 'notification_type'], unique=False)
        op.create_index('idx_notification_user_unread', 'in_app_notifications', ['user_id', 'is_read', 'is_dismissed'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_created_at'), 'in_app_notifications', ['created_at'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_id'), 'in_app_notifications', ['id'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_is_dismissed'), 'in_app_notifications', ['is_dismissed'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_is_read'), 'in_app_notifications', ['is_read'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_notification_type'), 'in_app_notifications', ['notification_type'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_user_id'), 'in_app_notifications', ['user_id'], unique=False)

    # Autonomy Settings
    if 'autonomy_settings' not in existing_tables:
        op.create_table('autonomy_settings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('action_type', sa.String(length=50), nullable=False),
            sa.Column('autonomy_level', sa.String(length=20), nullable=True),
            sa.Column('require_notification', sa.Boolean(), nullable=True),
            sa.Column('require_confirmation', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_autonomy_user_action', 'autonomy_settings', ['user_id', 'action_type'], unique=True)
        op.create_index(op.f('ix_autonomy_settings_id'), 'autonomy_settings', ['id'], unique=False)
        op.create_index(op.f('ix_autonomy_settings_user_id'), 'autonomy_settings', ['user_id'], unique=False)

    # Autonomous Actions
    if 'autonomous_actions' not in existing_tables:
        op.create_table('autonomous_actions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('action_type', sa.String(length=50), nullable=False),
            sa.Column('plan_data', sa.JSON(), nullable=False),
            sa.Column('goal_id', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('autonomy_level_used', sa.String(length=20), nullable=True),
            sa.Column('executed_at', sa.DateTime(), nullable=True),
            sa.Column('result', sa.JSON(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('requires_approval', sa.Boolean(), nullable=True),
            sa.Column('approved_by', sa.String(length=100), nullable=True),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            sa.Column('is_undoable', sa.Boolean(), nullable=True),
            sa.Column('undo_data', sa.JSON(), nullable=True),
            sa.Column('undone_at', sa.DateTime(), nullable=True),
            sa.Column('undo_expires_at', sa.DateTime(), nullable=True),
            sa.Column('notification_sent', sa.Boolean(), nullable=True),
            sa.Column('notification_channel', sa.String(length=50), nullable=True),
            sa.Column('notification_sent_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_action_pending_approval', 'autonomous_actions', ['user_id', 'status', 'requires_approval'], unique=False)
        op.create_index('idx_action_undoable', 'autonomous_actions', ['user_id', 'is_undoable', 'undo_expires_at'], unique=False)
        op.create_index('idx_action_user_status', 'autonomous_actions', ['user_id', 'status'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_action_type'), 'autonomous_actions', ['action_type'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_created_at'), 'autonomous_actions', ['created_at'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_executed_at'), 'autonomous_actions', ['executed_at'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_id'), 'autonomous_actions', ['id'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_status'), 'autonomous_actions', ['status'], unique=False)
        op.create_index(op.f('ix_autonomous_actions_user_id'), 'autonomous_actions', ['user_id'], unique=False)

    # Agent Goals
    if 'agent_goals' not in existing_tables:
        op.create_table('agent_goals',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('deadline', sa.DateTime(), nullable=True),
            sa.Column('context_tags', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_agent_goals_user_status', 'agent_goals', ['user_id', 'status'], unique=False)
        op.create_index(op.f('ix_agent_goals_id'), 'agent_goals', ['id'], unique=False)
        op.create_index(op.f('ix_agent_goals_status'), 'agent_goals', ['status'], unique=False)
        op.create_index(op.f('ix_agent_goals_user_id'), 'agent_goals', ['user_id'], unique=False)

    # Actionable Items
    if 'actionable_items' not in existing_tables:
        op.create_table('actionable_items',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('title', sa.String(length=500), nullable=False),
            sa.Column('item_type', sa.String(length=50), nullable=True),
            sa.Column('due_date', sa.DateTime(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=True),
            sa.Column('source_type', sa.String(length=50), nullable=True),
            sa.Column('source_id', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('urgency', sa.String(length=20), nullable=True),
            sa.Column('suggested_action', sa.String(length=100), nullable=True),
            sa.Column('extracted_at', sa.DateTime(), nullable=True),
            sa.Column('reminder_sent_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_actionable_user_status_due', 'actionable_items', ['user_id', 'status', 'due_date'], unique=False)
        op.create_index(op.f('ix_actionable_items_due_date'), 'actionable_items', ['due_date'], unique=False)
        op.create_index(op.f('ix_actionable_items_status'), 'actionable_items', ['status'], unique=False)
        op.create_index(op.f('ix_actionable_items_user_id'), 'actionable_items', ['user_id'], unique=False)

    # Template Tables
    for table_name in ['meeting_templates', 'task_templates', 'email_templates']:
        if table_name not in existing_tables:
            if table_name == 'meeting_templates':
                op.create_table('meeting_templates',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.Integer(), nullable=False),
                    sa.Column('name', sa.String(length=255), nullable=False),
                    sa.Column('title', sa.String(length=500), nullable=True),
                    sa.Column('duration_minutes', sa.Integer(), nullable=True),
                    sa.Column('description', sa.Text(), nullable=True),
                    sa.Column('location', sa.String(length=500), nullable=True),
                    sa.Column('default_attendees', sa.JSON(), nullable=True),
                    sa.Column('recurrence', sa.String(length=100), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
                    sa.PrimaryKeyConstraint('id')
                )
                op.create_index('idx_template_user_active', 'meeting_templates', ['user_id', 'is_active'], unique=False)
                op.create_index('idx_template_user_name', 'meeting_templates', ['user_id', 'name'], unique=True)
            elif table_name == 'task_templates':
                op.create_table('task_templates',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.Integer(), nullable=False),
                    sa.Column('name', sa.String(length=255), nullable=False),
                    sa.Column('description', sa.String(length=500), nullable=True),
                    sa.Column('task_description', sa.Text(), nullable=False),
                    sa.Column('priority', sa.String(length=20), nullable=True),
                    sa.Column('category', sa.String(length=100), nullable=True),
                    sa.Column('tags', sa.JSON(), nullable=True),
                    sa.Column('subtasks', sa.JSON(), nullable=True),
                    sa.Column('recurrence', sa.String(length=100), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
                    sa.PrimaryKeyConstraint('id')
                )
                op.create_index('idx_task_template_user_active', 'task_templates', ['user_id', 'is_active'], unique=False)
                op.create_index('idx_task_template_user_name', 'task_templates', ['user_id', 'name'], unique=True)
            elif table_name == 'email_templates':
                op.create_table('email_templates',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.Integer(), nullable=False),
                    sa.Column('name', sa.String(length=255), nullable=False),
                    sa.Column('subject', sa.String(length=500), nullable=True),
                    sa.Column('body', sa.Text(), nullable=False),
                    sa.Column('to_recipients', sa.JSON(), nullable=True),
                    sa.Column('cc_recipients', sa.JSON(), nullable=True),
                    sa.Column('bcc_recipients', sa.JSON(), nullable=True),
                    sa.Column('tone', sa.String(length=50), nullable=True),
                    sa.Column('category', sa.String(length=100), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
                    sa.PrimaryKeyConstraint('id')
                )
                op.create_index('idx_email_template_user_active', 'email_templates', ['user_id', 'is_active'], unique=False)
                op.create_index('idx_email_template_user_name', 'email_templates', ['user_id', 'name'], unique=True)

            op.create_index(op.f(f'ix_{table_name}_created_at'), table_name, ['created_at'], unique=False)
            op.create_index(op.f(f'ix_{table_name}_id'), table_name, ['id'], unique=False)
            op.create_index(op.f(f'ix_{table_name}_is_active'), table_name, ['is_active'], unique=False)
            op.create_index(op.f(f'ix_{table_name}_user_id'), table_name, ['user_id'], unique=False)

    # Clean up legacy tables (detected as drops by autogenerate)
    for table_to_drop in ['execution_memory', 'langchain_pg_embedding', 'langchain_pg_collection', 'query_patterns', 'api_keys']:
        if table_to_drop in existing_tables:
            if table_to_drop == 'langchain_pg_embedding':
                op.drop_index(op.f('ix_cmetadata_gin'), table_name='langchain_pg_embedding', postgresql_ops={'cmetadata': 'jsonb_path_ops'}, postgresql_using='gin')
            elif table_to_drop == 'api_keys':
                op.drop_index(op.f('idx_apikey_hash_active'), table_name='api_keys')
                op.drop_index(op.f('idx_apikey_user_active'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_created_at'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_expires_at'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_id'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_is_active'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
                op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
            
            op.drop_table(table_to_drop)

    # Interaction Sessions Updates
    inspector = inspect(conn)
    interaction_cols = [c['name'] for c in inspector.get_columns('interaction_sessions')]
    if 'session_context' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('session_context', sa.JSON(), nullable=True))
    if 'active_topics' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('active_topics', sa.JSON(), nullable=True))
    if 'last_intent' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('last_intent', sa.String(length=100), nullable=True))
    if 'turn_count' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('turn_count', sa.Integer(), nullable=True))
    if 'started_at' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    if 'avg_response_satisfaction' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('avg_response_satisfaction', sa.Float(), nullable=True))
    if 'escalation_count' not in interaction_cols:
        op.add_column('interaction_sessions', sa.Column('escalation_count', sa.Integer(), nullable=True))

    # User Integrations Updates
    user_integration_indexes = [ix['name'] for ix in inspector.get_indexes('user_integrations')]
    if 'idx_user_integrations_is_active' in user_integration_indexes:
         op.drop_index('idx_user_integrations_is_active', table_name='user_integrations')
    
    # Only create if doesn't exist
    existing_indexes = [ix['name'] for ix in inspector.get_indexes('user_integrations')]
    if 'ix_user_integrations_is_active' not in existing_indexes:
        op.create_index(op.f('ix_user_integrations_is_active'), 'user_integrations', ['is_active'], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_user_integrations_is_active'), table_name='user_integrations')
    op.create_index(op.f('idx_user_integrations_is_active'), 'user_integrations', ['is_active'], unique=False)
    op.drop_column('interaction_sessions', 'escalation_count')
    op.drop_column('interaction_sessions', 'avg_response_satisfaction')
    op.drop_column('interaction_sessions', 'started_at')
    op.drop_column('interaction_sessions', 'turn_count')
    op.drop_column('interaction_sessions', 'last_intent')
    op.drop_column('interaction_sessions', 'active_topics')
    op.drop_column('interaction_sessions', 'session_context')
    op.create_index(op.f('idx_agent_facts_category'), 'agent_facts', ['user_id', 'category'], unique=False)
    op.create_table('api_keys',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('key_hash', sa.VARCHAR(length=64), autoincrement=False, nullable=False),
    sa.Column('key_prefix', sa.VARCHAR(length=12), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(length=500), autoincrement=False, nullable=True),
    sa.Column('scopes', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('last_used_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('last_used_ip', sa.VARCHAR(length=45), autoincrement=False, nullable=True),
    sa.Column('usage_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('revoked_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('revoked_reason', sa.VARCHAR(length=200), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('api_keys_user_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('api_keys_pkey'))
    )
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)
    op.create_index(op.f('ix_api_keys_is_active'), 'api_keys', ['is_active'], unique=False)
    op.create_index(op.f('ix_api_keys_id'), 'api_keys', ['id'], unique=False)
    op.create_index(op.f('ix_api_keys_expires_at'), 'api_keys', ['expires_at'], unique=False)
    op.create_index(op.f('ix_api_keys_created_at'), 'api_keys', ['created_at'], unique=False)
    op.create_index(op.f('idx_apikey_user_active'), 'api_keys', ['user_id', 'is_active'], unique=False)
    op.create_index(op.f('idx_apikey_hash_active'), 'api_keys', ['key_hash', 'is_active'], unique=False)
    op.create_table('query_patterns',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('pattern', sa.VARCHAR(length=500), autoincrement=False, nullable=False),
    sa.Column('intent', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
    sa.Column('success_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('failure_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('confidence', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('last_used', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('query_patterns_pkey'))
    )
    op.create_table('langchain_pg_embedding',
    sa.Column('id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('collection_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('embedding', sa.NullType(), autoincrement=False, nullable=True),
    sa.Column('document', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('cmetadata', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['collection_id'], ['langchain_pg_collection.uuid'], name=op.f('langchain_pg_embedding_collection_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('langchain_pg_embedding_pkey'))
    )
    op.create_index(op.f('ix_cmetadata_gin'), 'langchain_pg_embedding', ['cmetadata'], unique=False, postgresql_ops={'cmetadata': 'jsonb_path_ops'}, postgresql_using='gin')
    op.create_table('langchain_pg_collection',
    sa.Column('uuid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('cmetadata', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('uuid', name=op.f('langchain_pg_collection_pkey')),
    sa.UniqueConstraint('name', name=op.f('langchain_pg_collection_name_key'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_table('execution_memory',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('query', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('tools_used', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('success', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('execution_time', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('step_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('execution_memory_pkey'))
    )
    # ### end Alembic commands ###
