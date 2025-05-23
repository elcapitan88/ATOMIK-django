"""add_billing_interval_to_subscription

Revision ID: 62d1d0deb00a
Revises: 307cd96563fc
Create Date: 2025-02-07 22:26:20.555769

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62d1d0deb00a'
down_revision: Union[str, None] = '307cd96563fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('subscriptions', sa.Column('billing_interval', sa.Enum('MONTHLY', 'YEARLY', 'LIFETIME', name='billinginterval'), nullable=False))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('subscriptions', 'billing_interval')
    # ### end Alembic commands ###
