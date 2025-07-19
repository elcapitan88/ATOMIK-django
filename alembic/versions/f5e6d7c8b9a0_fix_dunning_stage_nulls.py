"""fix_dunning_stage_nulls

Revision ID: f5e6d7c8b9a0
Revises: e4f5a6b7c8d9
Create Date: 2025-07-19 15:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5e6d7c8b9a0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix any NULL dunning_stage values that might exist
    op.execute("UPDATE subscriptions SET dunning_stage = 'none' WHERE dunning_stage IS NULL")
    

def downgrade() -> None:
    # No downgrade needed for data fix
    pass