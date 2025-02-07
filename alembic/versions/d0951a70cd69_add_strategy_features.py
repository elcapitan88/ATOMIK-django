# alembic/versions/d0951a70cd69_add_strategy_features.py

"""add_strategy_features

Revision ID: d0951a70cd69
Revises: d5363b7738fc
Create Date: 2025-02-05 12:03:47.067796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd0951a70cd69'
down_revision: Union[str, None] = 'd5363b7738fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create strategy type enum
    strategy_type = postgresql.ENUM('momentum', 'mean_reversion', 'breakout', 'arbitrage', 'scalping',
                                  name='strategytype')
    strategy_type.create(op.get_bind())

    # Add new columns to webhooks table
    op.add_column('webhooks', sa.Column('strategy_type', sa.Enum('momentum', 'mean_reversion', 'breakout', 
                                                                'arbitrage', 'scalping', 
                                                                name='strategytype'), 
                                                                nullable=True))
    op.add_column('webhooks', sa.Column('subscriber_count', sa.Integer(), server_default='0'))
    op.add_column('webhooks', sa.Column('rating', sa.Float(), server_default='0.0'))
    op.add_column('webhooks', sa.Column('total_ratings', sa.Integer(), server_default='0'))

    # Create index for better query performance
    op.create_index('ix_webhooks_is_shared', 'webhooks', ['is_shared'])

def downgrade() -> None:
    # Drop index
    op.drop_index('ix_webhooks_is_shared')
    
    # Drop new columns from webhooks table
    op.drop_column('webhooks', 'total_ratings')
    op.drop_column('webhooks', 'rating')
    op.drop_column('webhooks', 'subscriber_count')
    op.drop_column('webhooks', 'strategy_type')
    
    # Drop the enum type
    strategy_type = postgresql.ENUM('momentum', 'mean_reversion', 'breakout', 'arbitrage', 'scalping',
                                  name='strategytype')
    strategy_type.drop(op.get_bind())