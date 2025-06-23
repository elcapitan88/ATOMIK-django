"""add_trades_tables

Revision ID: 001_add_trades_tables
Revises: 183b34d3df5c
Create Date: 2025-06-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_add_trades_tables'
down_revision: Union[str, None] = '183b34d3df5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create trades table
    op.create_table('trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('strategy_id', sa.Integer(), nullable=True),
        sa.Column('position_id', sa.String(length=50), nullable=False),
        sa.Column('broker_id', sa.String(length=50), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('contract_id', sa.Integer(), nullable=True),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('total_quantity', sa.Integer(), nullable=False),
        sa.Column('average_entry_price', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('exit_price', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('realized_pnl', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('max_unrealized_pnl', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('max_adverse_pnl', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('open_time', sa.DateTime(), nullable=False),
        sa.Column('close_time', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('stop_loss_price', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('take_profit_price', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('broker_data', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('tags', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['strategy_id'], ['activated_strategies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('position_id')
    )
    
    # Create indexes for trades table
    op.create_index('idx_trades_user_strategy', 'trades', ['user_id', 'strategy_id'])
    op.create_index('idx_trades_symbol_time', 'trades', ['symbol', 'open_time'])
    op.create_index('idx_trades_status_time', 'trades', ['status', 'open_time'])
    op.create_index('idx_trades_user_time', 'trades', ['user_id', 'open_time'])
    op.create_index(op.f('ix_trades_broker_id'), 'trades', ['broker_id'])
    op.create_index(op.f('ix_trades_id'), 'trades', ['id'])
    op.create_index(op.f('ix_trades_open_time'), 'trades', ['open_time'])
    op.create_index(op.f('ix_trades_position_id'), 'trades', ['position_id'])
    op.create_index(op.f('ix_trades_status'), 'trades', ['status'])
    op.create_index(op.f('ix_trades_strategy_id'), 'trades', ['strategy_id'])
    op.create_index(op.f('ix_trades_symbol'), 'trades', ['symbol'])
    op.create_index(op.f('ix_trades_user_id'), 'trades', ['user_id'])

    # Create trade_executions table
    op.create_table('trade_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=False),
        sa.Column('broker_account_id', sa.String(), nullable=False),
        sa.Column('account_role', sa.String(length=20), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('execution_price', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('execution_time', sa.DateTime(), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('execution_id', sa.String(length=100), nullable=True),
        sa.Column('commission', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('fees', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('broker_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['broker_account_id'], ['broker_accounts.account_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for trade_executions table
    op.create_index('idx_executions_trade_account', 'trade_executions', ['trade_id', 'broker_account_id'])
    op.create_index('idx_executions_time', 'trade_executions', ['execution_time'])
    op.create_index(op.f('ix_trade_executions_id'), 'trade_executions', ['id'])
    op.create_index(op.f('ix_trade_executions_trade_id'), 'trade_executions', ['trade_id'])


def downgrade() -> None:
    # Drop indexes first
    op.drop_index(op.f('ix_trade_executions_trade_id'), table_name='trade_executions')
    op.drop_index(op.f('ix_trade_executions_id'), table_name='trade_executions')
    op.drop_index('idx_executions_time', table_name='trade_executions')
    op.drop_index('idx_executions_trade_account', table_name='trade_executions')
    
    # Drop trade_executions table
    op.drop_table('trade_executions')
    
    # Drop trades indexes
    op.drop_index(op.f('ix_trades_user_id'), table_name='trades')
    op.drop_index(op.f('ix_trades_symbol'), table_name='trades')
    op.drop_index(op.f('ix_trades_strategy_id'), table_name='trades')
    op.drop_index(op.f('ix_trades_status'), table_name='trades')
    op.drop_index(op.f('ix_trades_position_id'), table_name='trades')
    op.drop_index(op.f('ix_trades_open_time'), table_name='trades')
    op.drop_index(op.f('ix_trades_id'), table_name='trades')
    op.drop_index(op.f('ix_trades_broker_id'), table_name='trades')
    op.drop_index('idx_trades_user_time', table_name='trades')
    op.drop_index('idx_trades_status_time', table_name='trades')
    op.drop_index('idx_trades_symbol_time', table_name='trades')
    op.drop_index('idx_trades_user_strategy', table_name='trades')
    
    # Drop trades table
    op.drop_table('trades')