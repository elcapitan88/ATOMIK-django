"""Add profile picture and phone fields

Revision ID: 8393ced5bc4a
Revises: ad47e836f826
Create Date: 2025-05-24 17:07:15.865753

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8393ced5bc4a'
down_revision: Union[str, None] = 'ad47e836f826'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add profile_picture and phone columns to users table
    op.add_column('users', sa.Column('profile_picture', sa.String(), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove profile_picture and phone columns from users table
    op.drop_column('users', 'phone')
    op.drop_column('users', 'profile_picture')
