"""remove refresh token column

Revision ID: aa001
Revises: a79b6d518ec1
Create Date: 2025-01-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'aa001'
down_revision: Union[str, None] = 'a79b6d518ec1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove the refresh_token column
    with op.batch_alter_table('broker_credentials') as batch_op:
        batch_op.drop_column('refresh_token')


def downgrade() -> None:
    # Add back the refresh_token column if we need to downgrade
    with op.batch_alter_table('broker_credentials') as batch_op:
        batch_op.add_column(sa.Column('refresh_token', sa.String(), nullable=True))