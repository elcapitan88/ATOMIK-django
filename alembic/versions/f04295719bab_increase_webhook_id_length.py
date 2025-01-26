"""increase_webhook_id_length

Revision ID: <automatically_generated_id>
Revises: 0344bb8c1e66
Create Date: 2025-01-26 <current_time>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '<automatically_generated_id>'  # This will be automatically filled
down_revision: Union[str, None] = '0344bb8c1e66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase webhook_id column length to 64 to match webhook token length
    op.alter_column('activated_strategies', 'webhook_id',
                    existing_type=sa.String(length=36),
                    type_=sa.String(length=64),
                    existing_nullable=True)


def downgrade() -> None:
    # Revert column length
    op.alter_column('activated_strategies', 'webhook_id',
                    existing_type=sa.String(length=64),
                    type_=sa.String(length=36),
                    existing_nullable=True)