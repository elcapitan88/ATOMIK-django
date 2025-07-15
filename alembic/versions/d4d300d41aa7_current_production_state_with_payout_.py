"""current_production_state_with_payout_fields

Revision ID: d4d300d41aa7
Revises: 7997f0944830
Create Date: 2025-06-23 14:43:39.493996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4d300d41aa7'
down_revision: Union[str, None] = '7997f0944830'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
