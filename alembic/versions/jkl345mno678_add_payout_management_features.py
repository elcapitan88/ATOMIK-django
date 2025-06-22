"""Add payout management features

Revision ID: jkl345mno678
Revises: ghi012jkl345
Create Date: 2025-01-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'jkl345mno678'
down_revision: Union[str, None] = 'ghi012jkl345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add payout method fields to affiliates table
    op.add_column('affiliates', sa.Column('payout_method', sa.String(), nullable=True))
    op.add_column('affiliates', sa.Column('payout_details', sa.JSON(), nullable=True))
    
    # Create affiliate_payouts table
    op.create_table(
        'affiliate_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('payout_amount', sa.Float(), nullable=False),
        sa.Column('payout_method', sa.String(), nullable=False),
        sa.Column('payout_details', sa.JSON(), nullable=True),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('payout_date', sa.DateTime(), nullable=True),
        sa.Column('transaction_id', sa.String(), nullable=True),
        sa.Column('currency', sa.String(), server_default='USD', nullable=False),
        sa.Column('commission_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for better performance
    op.create_index('ix_affiliate_payouts_id', 'affiliate_payouts', ['id'])
    op.create_index('ix_affiliate_payouts_affiliate_id', 'affiliate_payouts', ['affiliate_id'])
    op.create_index('ix_affiliate_payouts_status', 'affiliate_payouts', ['status'])
    op.create_index('ix_affiliate_payouts_period_end', 'affiliate_payouts', ['period_end'])
    op.create_index('ix_affiliate_payouts_payout_date', 'affiliate_payouts', ['payout_date'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_affiliate_payouts_payout_date', table_name='affiliate_payouts')
    op.drop_index('ix_affiliate_payouts_period_end', table_name='affiliate_payouts')
    op.drop_index('ix_affiliate_payouts_status', table_name='affiliate_payouts')
    op.drop_index('ix_affiliate_payouts_affiliate_id', table_name='affiliate_payouts')
    op.drop_index('ix_affiliate_payouts_id', table_name='affiliate_payouts')
    
    # Drop affiliate_payouts table
    op.drop_table('affiliate_payouts')
    
    # Remove payout method columns from affiliates table
    op.drop_column('affiliates', 'payout_details')
    op.drop_column('affiliates', 'payout_method')