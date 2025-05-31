"""Add app_role to users

Revision ID: abc123def456
Revises: fe578aee2d61
Create Date: 2025-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abc123def456'
down_revision: Union[str, None] = 'fe578aee2d61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add app_role column to users table
    op.add_column('users', sa.Column('app_role', sa.String(), nullable=True))
    
    # Migrate existing is_superuser data to app_role
    # Users with is_superuser=True become app_role='admin'
    op.execute("UPDATE users SET app_role = 'admin' WHERE is_superuser = true")
    
    # Drop the old is_superuser column
    op.drop_column('users', 'is_superuser')


def downgrade() -> None:
    # Add back is_superuser column
    op.add_column('users', sa.Column('is_superuser', sa.Boolean(), default=False, nullable=False))
    
    # Migrate app_role data back to is_superuser
    # Users with app_role='admin' become is_superuser=True
    op.execute("UPDATE users SET is_superuser = true WHERE app_role = 'admin'")
    
    # Drop app_role column
    op.drop_column('users', 'app_role')