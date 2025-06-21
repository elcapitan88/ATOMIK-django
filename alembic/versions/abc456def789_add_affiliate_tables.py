"""add_affiliate_tables

Revision ID: abc456def789
Revises: 203319656625
Create Date: 2025-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abc456def789'
down_revision: Union[str, None] = '203319656625'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create affiliates table
    op.create_table(
        'affiliates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('firstpromoter_id', sa.String(), nullable=True),
        sa.Column('referral_link', sa.String(), nullable=True),
        sa.Column('referral_code', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('total_referrals', sa.Integer(), default=0, nullable=False),
        sa.Column('total_clicks', sa.Integer(), default=0, nullable=False),
        sa.Column('total_commissions_earned', sa.Float(), default=0.0, nullable=False),
        sa.Column('total_commissions_paid', sa.Float(), default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('firstpromoter_id'),
        sa.UniqueConstraint('referral_code')
    )
    
    # Create affiliate_referrals table
    op.create_table(
        'affiliate_referrals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('referred_user_id', sa.Integer(), nullable=True),
        sa.Column('firstpromoter_referral_id', sa.String(), nullable=True),
        sa.Column('customer_email', sa.String(), nullable=False),
        sa.Column('customer_name', sa.String(), nullable=True),
        sa.Column('conversion_amount', sa.Float(), nullable=True),
        sa.Column('commission_amount', sa.Float(), nullable=True),
        sa.Column('commission_rate', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), default='pending', nullable=False),
        sa.Column('is_first_conversion', sa.Boolean(), default=True, nullable=False),
        sa.Column('subscription_type', sa.String(), nullable=True),
        sa.Column('subscription_tier', sa.String(), nullable=True),
        sa.Column('referral_date', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('conversion_date', sa.DateTime(), nullable=True),
        sa.Column('commission_paid_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('firstpromoter_referral_id')
    )
    
    # Create affiliate_clicks table
    op.create_table(
        'affiliate_clicks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('referrer_url', sa.String(), nullable=True),
        sa.Column('landing_page', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('converted', sa.Boolean(), default=False, nullable=False),
        sa.Column('conversion_date', sa.DateTime(), nullable=True),
        sa.Column('click_date', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for better performance
    op.create_index('ix_affiliates_id', 'affiliates', ['id'])
    op.create_index('ix_affiliates_user_id', 'affiliates', ['user_id'])
    op.create_index('ix_affiliates_firstpromoter_id', 'affiliates', ['firstpromoter_id'])
    op.create_index('ix_affiliates_referral_code', 'affiliates', ['referral_code'])
    op.create_index('ix_affiliates_is_active', 'affiliates', ['is_active'])
    
    op.create_index('ix_affiliate_referrals_id', 'affiliate_referrals', ['id'])
    op.create_index('ix_affiliate_referrals_affiliate_id', 'affiliate_referrals', ['affiliate_id'])
    op.create_index('ix_affiliate_referrals_customer_email', 'affiliate_referrals', ['customer_email'])
    op.create_index('ix_affiliate_referrals_firstpromoter_referral_id', 'affiliate_referrals', ['firstpromoter_referral_id'])
    op.create_index('ix_affiliate_referrals_status', 'affiliate_referrals', ['status'])
    op.create_index('ix_affiliate_referrals_referral_date', 'affiliate_referrals', ['referral_date'])
    
    op.create_index('ix_affiliate_clicks_id', 'affiliate_clicks', ['id'])
    op.create_index('ix_affiliate_clicks_affiliate_id', 'affiliate_clicks', ['affiliate_id'])
    op.create_index('ix_affiliate_clicks_converted', 'affiliate_clicks', ['converted'])
    op.create_index('ix_affiliate_clicks_click_date', 'affiliate_clicks', ['click_date'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_affiliate_clicks_click_date', table_name='affiliate_clicks')
    op.drop_index('ix_affiliate_clicks_converted', table_name='affiliate_clicks')
    op.drop_index('ix_affiliate_clicks_affiliate_id', table_name='affiliate_clicks')
    op.drop_index('ix_affiliate_clicks_id', table_name='affiliate_clicks')
    
    op.drop_index('ix_affiliate_referrals_referral_date', table_name='affiliate_referrals')
    op.drop_index('ix_affiliate_referrals_status', table_name='affiliate_referrals')
    op.drop_index('ix_affiliate_referrals_firstpromoter_referral_id', table_name='affiliate_referrals')
    op.drop_index('ix_affiliate_referrals_customer_email', table_name='affiliate_referrals')
    op.drop_index('ix_affiliate_referrals_affiliate_id', table_name='affiliate_referrals')
    op.drop_index('ix_affiliate_referrals_id', table_name='affiliate_referrals')
    
    op.drop_index('ix_affiliates_is_active', table_name='affiliates')
    op.drop_index('ix_affiliates_referral_code', table_name='affiliates')
    op.drop_index('ix_affiliates_firstpromoter_id', table_name='affiliates')
    op.drop_index('ix_affiliates_user_id', table_name='affiliates')
    op.drop_index('ix_affiliates_id', table_name='affiliates')
    
    # Drop tables in reverse order (to respect foreign key constraints)
    op.drop_table('affiliate_clicks')
    op.drop_table('affiliate_referrals')
    op.drop_table('affiliates')