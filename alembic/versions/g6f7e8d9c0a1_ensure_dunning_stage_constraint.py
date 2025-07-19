"""ensure_dunning_stage_constraint

Revision ID: g6f7e8d9c0a1
Revises: f5e6d7c8b9a0
Create Date: 2025-07-19 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g6f7e8d9c0a1'
down_revision: Union[str, None] = 'f5e6d7c8b9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure all dunning_stage values are valid
    op.execute("""
        UPDATE subscriptions 
        SET dunning_stage = 'none' 
        WHERE dunning_stage IS NULL 
           OR dunning_stage NOT IN ('none', 'warning', 'urgent', 'final', 'suspended')
    """)
    
    # Add check constraint to ensure only valid enum values
    op.execute("""
        ALTER TABLE subscriptions 
        ADD CONSTRAINT check_dunning_stage_valid 
        CHECK (dunning_stage IN ('none', 'warning', 'urgent', 'final', 'suspended'))
    """)


def downgrade() -> None:
    # Remove check constraint
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS check_dunning_stage_valid")