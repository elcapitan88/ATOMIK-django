"""Add Rewardful fields to affiliate tables

Revision ID: def789ghi012
Revises: abc456def789
Create Date: 2025-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'def789ghi012'
down_revision = 'abc456def789'
branch_labels = None
depends_on = None


def upgrade():
    # Add rewardful_id to affiliates table
    op.add_column('affiliates', sa.Column('rewardful_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_affiliates_rewardful_id'), 'affiliates', ['rewardful_id'], unique=False)
    
    # Add rewardful_referral_id to affiliate_referrals table
    op.add_column('affiliate_referrals', sa.Column('rewardful_referral_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_affiliate_referrals_rewardful_referral_id'), 'affiliate_referrals', ['rewardful_referral_id'], unique=False)


def downgrade():
    # Remove indexes first
    op.drop_index(op.f('ix_affiliate_referrals_rewardful_referral_id'), table_name='affiliate_referrals')
    op.drop_index(op.f('ix_affiliates_rewardful_id'), table_name='affiliates')
    
    # Remove columns
    op.drop_column('affiliate_referrals', 'rewardful_referral_id')
    op.drop_column('affiliates', 'rewardful_id')