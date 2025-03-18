"""add_subscription_resource_tracking

Revision ID: 3faac94c8667
Revises: 4a29f9366e8f
Create Date: 2025-03-16 01:09:47.659204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3faac94c8667'
down_revision: Union[str, None] = '4a29f9366e8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add resource tracking columns to the subscriptions table
    op.add_column('subscriptions', sa.Column('connected_accounts_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('subscriptions', sa.Column('active_webhooks_count', sa.Integer(), nullable=True, server_default='0')) 
    op.add_column('subscriptions', sa.Column('active_strategies_count', sa.Integer(), nullable=True, server_default='0'))
    
    # Execute SQL to initialize these columns for existing subscriptions
    op.execute("""
    UPDATE subscriptions 
    SET connected_accounts_count = (
        SELECT COUNT(*) 
        FROM broker_accounts 
        WHERE broker_accounts.user_id = subscriptions.user_id 
        AND broker_accounts.is_active = TRUE 
        AND (broker_accounts.is_deleted = FALSE OR broker_accounts.is_deleted IS NULL)
    )
    """)
    
    op.execute("""
    UPDATE subscriptions 
    SET active_webhooks_count = (
        SELECT COUNT(*) 
        FROM webhooks 
        WHERE webhooks.user_id = subscriptions.user_id 
        AND webhooks.is_active = TRUE
    )
    """)
    
    op.execute("""
    UPDATE subscriptions 
    SET active_strategies_count = (
        SELECT COUNT(*) 
        FROM activated_strategies 
        WHERE activated_strategies.user_id = subscriptions.user_id 
        AND activated_strategies.is_active = TRUE
    )
    """)


def downgrade() -> None:
    # Remove columns added in the upgrade
    op.drop_column('subscriptions', 'connected_accounts_count')
    op.drop_column('subscriptions', 'active_webhooks_count')
    op.drop_column('subscriptions', 'active_strategies_count')