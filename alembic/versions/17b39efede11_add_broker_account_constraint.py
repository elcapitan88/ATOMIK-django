"""add_broker_account_constraint

Revision ID: 17b39efede11
Revises: 48f8520d6334
Create Date: 2025-01-14 11:28:31.534374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17b39efede11'
down_revision: Union[str, None] = '48f8520d6334'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_unique_constraint(
        'uq_user_account_broker_env',
        'broker_accounts',
        ['user_id', 'account_id', 'broker_id', 'environment']
    )

def downgrade():
    op.drop_constraint(
        'uq_user_account_broker_env',
        'broker_accounts',
        type_='unique'
    )