"""add_sharing_and_description

Revision ID: a4365b1409fa
Revises: f2bb6cf50c5c
Create Date: 2025-01-31 18:15:02.725344

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4365b1409fa'
down_revision: Union[str, None] = 'f2bb6cf50c5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # First, drop the foreign key constraint
    op.execute("""
        ALTER TABLE activated_strategies 
        DROP CONSTRAINT IF EXISTS fk_activated_strategies_leader_account;
    """)

    # Add new columns to webhooks table
    op.add_column('webhooks', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('webhooks', sa.Column('is_shared', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('webhooks', sa.Column('sharing_enabled_at', sa.DateTime(), nullable=True))

    # Keep leader_account_id as VARCHAR to match account_id
    # No need to alter the column type if they should match

def downgrade() -> None:
    # Remove added columns from webhooks
    op.drop_column('webhooks', 'sharing_enabled_at')
    op.drop_column('webhooks', 'is_shared')
    op.drop_column('webhooks', 'description')

    # Recreate the foreign key constraint if needed
    op.create_foreign_key(
        'fk_activated_strategies_leader_account',
        'activated_strategies',
        'broker_accounts',
        ['leader_account_id'],
        ['account_id']
    )