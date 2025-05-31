"""add_chat_system_tables

Revision ID: 930a84d6680c
Revises: fe578aee2d61
Create Date: 2025-05-30 17:58:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '930a84d6680c'
down_revision: Union[str, None] = '8393ced5bc4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create chat_channels table
    op.create_table(
        'chat_channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_general', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('sort_order', sa.Integer(), default=0, nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create chat_messages table
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('original_content', sa.Text(), nullable=True),
        sa.Column('is_edited', sa.Boolean(), default=False, nullable=False),
        sa.Column('edited_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('reply_to_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['chat_channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reply_to_id'], ['chat_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create chat_reactions table
    op.create_table(
        'chat_reactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('emoji', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'user_id', 'emoji', name='unique_reaction_per_user')
    )
    
    # Create user_chat_roles table
    op.create_table(
        'user_chat_roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_name', sa.String(50), nullable=False),
        sa.Column('role_color', sa.String(7), nullable=False),
        sa.Column('role_priority', sa.Integer(), default=0, nullable=False),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create user_chat_settings table
    op.create_table(
        'user_chat_settings',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('show_profile_pictures', sa.Boolean(), default=True, nullable=False),
        sa.Column('notification_sound', sa.Boolean(), default=True, nullable=False),
        sa.Column('compact_mode', sa.Boolean(), default=False, nullable=False),
        sa.Column('theme', sa.String(20), default='dark', nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # Create chat_channel_members table
    op.create_table(
        'chat_channel_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('joined_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('last_read_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('is_muted', sa.Boolean(), default=False, nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['chat_channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'user_id', name='unique_channel_member')
    )
    
    # Create indexes for better performance
    op.create_index('ix_chat_channels_id', 'chat_channels', ['id'])
    op.create_index('ix_chat_channels_name', 'chat_channels', ['name'])
    op.create_index('ix_chat_channels_is_active', 'chat_channels', ['is_active'])
    
    op.create_index('ix_chat_messages_id', 'chat_messages', ['id'])
    op.create_index('ix_chat_messages_channel_id', 'chat_messages', ['channel_id'])
    op.create_index('ix_chat_messages_user_id', 'chat_messages', ['user_id'])
    op.create_index('ix_chat_messages_created_at', 'chat_messages', ['created_at'])
    op.create_index('ix_chat_messages_is_deleted', 'chat_messages', ['is_deleted'])
    
    op.create_index('ix_chat_reactions_message_id', 'chat_reactions', ['message_id'])
    op.create_index('ix_chat_reactions_user_id', 'chat_reactions', ['user_id'])
    
    op.create_index('ix_user_chat_roles_user_id', 'user_chat_roles', ['user_id'])
    op.create_index('ix_user_chat_roles_is_active', 'user_chat_roles', ['is_active'])
    op.create_index('ix_user_chat_roles_priority', 'user_chat_roles', ['role_priority'])
    
    op.create_index('ix_chat_channel_members_channel_id', 'chat_channel_members', ['channel_id'])
    op.create_index('ix_chat_channel_members_user_id', 'chat_channel_members', ['user_id'])
    op.create_index('ix_chat_channel_members_last_read', 'chat_channel_members', ['last_read_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_chat_channel_members_last_read', table_name='chat_channel_members')
    op.drop_index('ix_chat_channel_members_user_id', table_name='chat_channel_members')
    op.drop_index('ix_chat_channel_members_channel_id', table_name='chat_channel_members')
    
    op.drop_index('ix_user_chat_roles_priority', table_name='user_chat_roles')
    op.drop_index('ix_user_chat_roles_is_active', table_name='user_chat_roles')
    op.drop_index('ix_user_chat_roles_user_id', table_name='user_chat_roles')
    
    op.drop_index('ix_chat_reactions_user_id', table_name='chat_reactions')
    op.drop_index('ix_chat_reactions_message_id', table_name='chat_reactions')
    
    op.drop_index('ix_chat_messages_is_deleted', table_name='chat_messages')
    op.drop_index('ix_chat_messages_created_at', table_name='chat_messages')
    op.drop_index('ix_chat_messages_user_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_channel_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_id', table_name='chat_messages')
    
    op.drop_index('ix_chat_channels_is_active', table_name='chat_channels')
    op.drop_index('ix_chat_channels_name', table_name='chat_channels')
    op.drop_index('ix_chat_channels_id', table_name='chat_channels')
    
    # Drop tables in reverse order (to respect foreign key constraints)
    op.drop_table('chat_channel_members')
    op.drop_table('user_chat_settings')
    op.drop_table('user_chat_roles')
    op.drop_table('chat_reactions')
    op.drop_table('chat_messages')
    op.drop_table('chat_channels')