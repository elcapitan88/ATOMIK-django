"""Remove FirstPromoter columns from affiliate tables

Revision ID: ghi012jkl345
Revises: def789ghi012
Create Date: 2025-01-01 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ghi012jkl345'
down_revision = 'def789ghi012'
branch_labels = None
depends_on = None


def upgrade():
    # Remove FirstPromoter columns from affiliates table
    op.drop_index(op.f('ix_affiliates_firstpromoter_id'), table_name='affiliates')
    op.drop_column('affiliates', 'firstpromoter_id')
    
    # Remove FirstPromoter columns from affiliate_referrals table
    op.drop_index(op.f('ix_affiliate_referrals_firstpromoter_referral_id'), table_name='affiliate_referrals')
    op.drop_column('affiliate_referrals', 'firstpromoter_referral_id')


def downgrade():
    # Re-add FirstPromoter columns to affiliate_referrals table
    op.add_column('affiliate_referrals', sa.Column('firstpromoter_referral_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_affiliate_referrals_firstpromoter_referral_id'), 'affiliate_referrals', ['firstpromoter_referral_id'], unique=True)
    
    # Re-add FirstPromoter columns to affiliates table
    op.add_column('affiliates', sa.Column('firstpromoter_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_affiliates_firstpromoter_id'), 'affiliates', ['firstpromoter_id'], unique=True)