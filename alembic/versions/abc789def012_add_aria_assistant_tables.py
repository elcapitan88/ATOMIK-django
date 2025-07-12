"""add_aria_assistant_tables

Revision ID: abc789def012
Revises: fe578aee2d61
Create Date: 2025-01-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'abc789def012'
down_revision = 'jkl345mno678'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_trading_profiles table
    op.create_table('user_trading_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('total_trades', sa.Integer(), nullable=True),
        sa.Column('win_rate', sa.Float(), nullable=True),
        sa.Column('avg_hold_time', sa.Integer(), nullable=True),
        sa.Column('avg_profit_per_trade', sa.Float(), nullable=True),
        sa.Column('avg_loss_per_trade', sa.Float(), nullable=True),
        sa.Column('preferred_timeframes', sa.JSON(), nullable=True),
        sa.Column('preferred_instruments', sa.JSON(), nullable=True),
        sa.Column('risk_tolerance', sa.String(), nullable=True),
        sa.Column('max_position_size', sa.Float(), nullable=True),
        sa.Column('preferred_brokers', sa.JSON(), nullable=True),
        sa.Column('best_trading_hours', sa.JSON(), nullable=True),
        sa.Column('worst_trading_days', sa.JSON(), nullable=True),
        sa.Column('monthly_performance', sa.JSON(), nullable=True),
        sa.Column('seasonal_patterns', sa.JSON(), nullable=True),
        sa.Column('revenge_trading_tendency', sa.Float(), nullable=True),
        sa.Column('overtrading_tendency', sa.Float(), nullable=True),
        sa.Column('risk_management_score', sa.Float(), nullable=True),
        sa.Column('emotional_trading_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_analysis_update', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_trading_profiles_id'), 'user_trading_profiles', ['id'], unique=False)
    op.create_index(op.f('ix_user_trading_profiles_user_id'), 'user_trading_profiles', ['user_id'], unique=True)

    # Create user_trading_sessions table
    op.create_table('user_trading_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_profile_id', sa.Integer(), nullable=True),
        sa.Column('session_date', sa.Date(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('session_duration', sa.Integer(), nullable=True),
        sa.Column('total_trades', sa.Integer(), nullable=True),
        sa.Column('winning_trades', sa.Integer(), nullable=True),
        sa.Column('losing_trades', sa.Integer(), nullable=True),
        sa.Column('session_pnl', sa.Float(), nullable=True),
        sa.Column('largest_winner', sa.Float(), nullable=True),
        sa.Column('largest_loser', sa.Float(), nullable=True),
        sa.Column('max_drawdown', sa.Float(), nullable=True),
        sa.Column('market_conditions', sa.JSON(), nullable=True),
        sa.Column('active_strategies', sa.JSON(), nullable=True),
        sa.Column('brokers_used', sa.JSON(), nullable=True),
        sa.Column('emotions_detected', sa.JSON(), nullable=True),
        sa.Column('trading_mistakes', sa.JSON(), nullable=True),
        sa.Column('session_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_profile_id'], ['user_trading_profiles.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_trading_sessions_id'), 'user_trading_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_user_trading_sessions_session_date'), 'user_trading_sessions', ['session_date'], unique=False)
    op.create_index(op.f('ix_user_trading_sessions_user_profile_id'), 'user_trading_sessions', ['user_profile_id'], unique=False)

    # Create aria_interactions table
    op.create_table('aria_interactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_profile_id', sa.Integer(), nullable=True),
        sa.Column('trading_session_id', sa.Integer(), nullable=True),
        sa.Column('interaction_type', sa.String(), nullable=True),
        sa.Column('input_method', sa.String(), nullable=True),
        sa.Column('raw_input', sa.Text(), nullable=True),
        sa.Column('processed_command', sa.Text(), nullable=True),
        sa.Column('detected_intent', sa.String(), nullable=True),
        sa.Column('intent_confidence', sa.Float(), nullable=True),
        sa.Column('intent_parameters', sa.JSON(), nullable=True),
        sa.Column('ai_model_used', sa.String(), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('context_used', sa.JSON(), nullable=True),
        sa.Column('aria_response', sa.Text(), nullable=True),
        sa.Column('response_type', sa.String(), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('action_attempted', sa.String(), nullable=True),
        sa.Column('action_parameters', sa.JSON(), nullable=True),
        sa.Column('action_success', sa.Boolean(), nullable=True),
        sa.Column('action_result', sa.JSON(), nullable=True),
        sa.Column('user_satisfaction', sa.Integer(), nullable=True),
        sa.Column('user_feedback', sa.Text(), nullable=True),
        sa.Column('followup_needed', sa.Boolean(), nullable=True),
        sa.Column('required_confirmation', sa.Boolean(), nullable=True),
        sa.Column('confirmation_provided', sa.Boolean(), nullable=True),
        sa.Column('risk_level', sa.String(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('response_timestamp', sa.DateTime(), nullable=True),
        sa.Column('action_timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['trading_session_id'], ['user_trading_sessions.id'], ),
        sa.ForeignKeyConstraint(['user_profile_id'], ['user_trading_profiles.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_aria_interactions_id'), 'aria_interactions', ['id'], unique=False)
    op.create_index(op.f('ix_aria_interactions_interaction_type'), 'aria_interactions', ['interaction_type'], unique=False)
    op.create_index(op.f('ix_aria_interactions_timestamp'), 'aria_interactions', ['timestamp'], unique=False)
    op.create_index(op.f('ix_aria_interactions_trading_session_id'), 'aria_interactions', ['trading_session_id'], unique=False)
    op.create_index(op.f('ix_aria_interactions_user_profile_id'), 'aria_interactions', ['user_profile_id'], unique=False)

    # Create aria_context_cache table
    op.create_table('aria_context_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('cache_key', sa.String(), nullable=True),
        sa.Column('cache_data', sa.JSON(), nullable=True),
        sa.Column('cache_timestamp', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('data_source', sa.String(), nullable=True),
        sa.Column('cache_hit_count', sa.Integer(), nullable=True),
        sa.Column('last_accessed', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_aria_context_cache_cache_key'), 'aria_context_cache', ['cache_key'], unique=False)
    op.create_index(op.f('ix_aria_context_cache_expires_at'), 'aria_context_cache', ['expires_at'], unique=False)
    op.create_index(op.f('ix_aria_context_cache_id'), 'aria_context_cache', ['id'], unique=False)
    op.create_index(op.f('ix_aria_context_cache_user_id'), 'aria_context_cache', ['user_id'], unique=False)


def downgrade():
    # Drop ARIA tables in reverse order
    op.drop_index(op.f('ix_aria_context_cache_user_id'), table_name='aria_context_cache')
    op.drop_index(op.f('ix_aria_context_cache_id'), table_name='aria_context_cache')
    op.drop_index(op.f('ix_aria_context_cache_expires_at'), table_name='aria_context_cache')
    op.drop_index(op.f('ix_aria_context_cache_cache_key'), table_name='aria_context_cache')
    op.drop_table('aria_context_cache')
    
    op.drop_index(op.f('ix_aria_interactions_user_profile_id'), table_name='aria_interactions')
    op.drop_index(op.f('ix_aria_interactions_trading_session_id'), table_name='aria_interactions')
    op.drop_index(op.f('ix_aria_interactions_timestamp'), table_name='aria_interactions')
    op.drop_index(op.f('ix_aria_interactions_interaction_type'), table_name='aria_interactions')
    op.drop_index(op.f('ix_aria_interactions_id'), table_name='aria_interactions')
    op.drop_table('aria_interactions')
    
    op.drop_index(op.f('ix_user_trading_sessions_user_profile_id'), table_name='user_trading_sessions')
    op.drop_index(op.f('ix_user_trading_sessions_session_date'), table_name='user_trading_sessions')
    op.drop_index(op.f('ix_user_trading_sessions_id'), table_name='user_trading_sessions')
    op.drop_table('user_trading_sessions')
    
    op.drop_index(op.f('ix_user_trading_profiles_user_id'), table_name='user_trading_profiles')
    op.drop_index(op.f('ix_user_trading_profiles_id'), table_name='user_trading_profiles')
    op.drop_table('user_trading_profiles')