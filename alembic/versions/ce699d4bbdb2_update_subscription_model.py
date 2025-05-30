"""update_subscription_model

Revision ID: ce699d4bbdb2
Revises: 28aac9cac1e0
Create Date: 2025-02-10 23:16:26.682627

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce699d4bbdb2'
down_revision: Union[str, None] = '28aac9cac1e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('subscriptions', sa.Column('status', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('updated_at', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('subscriptions', 'updated_at')
    op.drop_column('subscriptions', 'created_at')
    op.drop_column('subscriptions', 'status')
    # ### end Alembic commands ###
