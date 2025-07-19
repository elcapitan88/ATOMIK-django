"""add_payment_failure_tracking_fields

Revision ID: e4f5a6b7c8d9
Revises: d4d300d41aa7
Create Date: 2025-07-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = '002_add_maintenance_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum for dunning stages
    dunning_stage_enum = postgresql.ENUM(
        'none', 'warning', 'urgent', 'final', 'suspended',
        name='dunningstage'
    )
    dunning_stage_enum.create(op.get_bind())
    
    # Add payment failure tracking columns to subscriptions table
    op.add_column('subscriptions', sa.Column('payment_failed_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('payment_failure_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('subscriptions', sa.Column('grace_period_ends_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('last_payment_failure_reason', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('dunning_stage', dunning_stage_enum, nullable=False, server_default='none'))


def downgrade() -> None:
    # Remove payment failure tracking columns
    op.drop_column('subscriptions', 'dunning_stage')
    op.drop_column('subscriptions', 'last_payment_failure_reason')
    op.drop_column('subscriptions', 'grace_period_ends_at')
    op.drop_column('subscriptions', 'payment_failure_count')
    op.drop_column('subscriptions', 'payment_failed_at')
    
    # Drop enum
    op.execute('DROP TYPE dunningstage')