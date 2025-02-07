"""update_account_id_type

Revision ID: 4c8f07501550
Revises: adecf4b21951
Create Date: 2025-02-03 14:22:49.725139
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4c8f07501550'
down_revision: Union[str, None] = 'adecf4b21951'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # First drop existing foreign key constraints
    op.drop_constraint('strategy_follower_quantities_strategy_id_fkey', 'strategy_follower_quantities', type_='foreignkey')
    op.drop_constraint('strategy_follower_quantities_account_id_fkey', 'strategy_follower_quantities', type_='foreignkey')

    # Modify the account_id column type
    with op.batch_alter_table('strategy_follower_quantities') as batch_op:
        batch_op.alter_column('account_id',
                            existing_type=sa.Integer(),
                            type_=sa.String(),
                            postgresql_using="account_id::varchar")

    # Recreate foreign key constraints with CASCADE delete
    op.create_foreign_key(
        'strategy_follower_quantities_account_id_fkey',  # Named constraint for better tracking
        'strategy_follower_quantities',
        'broker_accounts',
        ['account_id'],
        ['account_id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'strategy_follower_quantities_strategy_id_fkey',  # Named constraint for better tracking
        'strategy_follower_quantities',
        'activated_strategies',
        ['strategy_id'],
        ['id'],
        ondelete='CASCADE'
    )

def downgrade() -> None:
    # Drop the foreign key constraints
    op.drop_constraint('strategy_follower_quantities_strategy_id_fkey', 'strategy_follower_quantities', type_='foreignkey')
    op.drop_constraint('strategy_follower_quantities_account_id_fkey', 'strategy_follower_quantities', type_='foreignkey')

    # Convert the account_id column back to integer
    with op.batch_alter_table('strategy_follower_quantities') as batch_op:
        batch_op.alter_column('account_id',
                            existing_type=sa.String(),
                            type_=sa.Integer(),
                            postgresql_using="account_id::integer")

    # Recreate original foreign key constraints without CASCADE
    op.create_foreign_key(
        'strategy_follower_quantities_account_id_fkey',
        'strategy_follower_quantities',
        'broker_accounts',
        ['account_id'],
        ['account_id']
    )
    op.create_foreign_key(
        'strategy_follower_quantities_strategy_id_fkey',
        'strategy_follower_quantities',
        'activated_strategies',
        ['strategy_id'],
        ['id']
    )