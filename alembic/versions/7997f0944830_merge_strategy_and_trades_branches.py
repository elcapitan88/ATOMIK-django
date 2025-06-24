"""merge_strategy_and_trades_branches

Revision ID: 7997f0944830
Revises: 001a2b3c4d5e, d0951a70cd69
Create Date: 2025-06-23 14:29:05.646396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7997f0944830'
down_revision: Union[str, None] = ('001a2b3c4d5e', 'd0951a70cd69')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
