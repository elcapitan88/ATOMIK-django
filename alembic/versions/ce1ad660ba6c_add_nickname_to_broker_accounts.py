"""add_nickname_to_broker_accounts

Revision ID: ce1ad660ba6c
Revises: fe578aee2d61
Create Date: 2025-02-27 13:13:36.611757

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce1ad660ba6c'
down_revision: Union[str, None] = 'fe578aee2d61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('broker_accounts', sa.Column('nickname', sa.String(200), nullable=True))

def downgrade():
    op.drop_column('broker_accounts', 'nickname')
