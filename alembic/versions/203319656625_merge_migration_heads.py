"""merge_migration_heads

Revision ID: 203319656625
Revises: 930a84d6680c, abc123def456
Create Date: 2025-05-31 10:12:21.566509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '203319656625'
down_revision: Union[str, None] = ('930a84d6680c', 'abc123def456')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
