"""add_resource_count_columns

Revision ID: cf4213541fe2
Revises: 6ab3579fcb7c
Create Date: 2025-03-17 18:23:11.002532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf4213541fe2'
down_revision: Union[str, None] = '6ab3579fcb7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the resource count columns to the subscriptions table
    op.add_column('subscriptions', sa.Column('connected_accounts_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('subscriptions', sa.Column('active_webhooks_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('subscriptions', sa.Column('active_strategies_count', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    # Remove columns if downgrading
    op.drop_column('subscriptions', 'connected_accounts_count')
    op.drop_column('subscriptions', 'active_webhooks_count')
    op.drop_column('subscriptions', 'active_strategies_count')