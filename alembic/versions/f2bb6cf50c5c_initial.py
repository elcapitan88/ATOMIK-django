"""initial

Revision ID: f2bb6cf50c5c
Revises: 
Create Date: 2025-01-31 15:21:16.412602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2bb6cf50c5c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First modify broker_accounts table and add unique constraint
    op.alter_column('broker_accounts', 'account_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=False)
    op.create_unique_constraint(
        'uq_broker_accounts_account_id', 
        'broker_accounts', 
        ['account_id']
    )

    # Then modify both account_id columns in activated_strategies
    op.alter_column('activated_strategies', 'account_id',
               existing_type=sa.INTEGER(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('activated_strategies', 'leader_account_id',
               existing_type=sa.INTEGER(),
               type_=sa.String(),
               existing_nullable=True)
    
    # Drop existing webhook foreign key
    op.drop_constraint('activated_strategies_webhook_id_fkey', 'activated_strategies', type_='foreignkey')
    
    # Create foreign keys after columns are converted
    op.create_foreign_key('fk_activated_strategies_account_id', 
                         'activated_strategies', 'broker_accounts', 
                         ['account_id'], ['account_id'], 
                         ondelete='CASCADE')
    op.create_foreign_key('fk_activated_strategies_leader_account', 
                         'activated_strategies', 'broker_accounts',
                         ['leader_account_id'], ['account_id'], 
                         ondelete='CASCADE')
    op.create_foreign_key('fk_activated_strategies_webhook', 
                         'activated_strategies', 'webhooks',
                         ['webhook_id'], ['token'])

    # Finally modify webhooks columns
    op.alter_column('webhooks', 'token',
               existing_type=sa.VARCHAR(length=64),
               nullable=False)
    op.alter_column('webhooks', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)

def downgrade() -> None:
    # Drop foreign keys first
    op.drop_constraint('fk_activated_strategies_webhook', 'activated_strategies', type_='foreignkey')
    op.drop_constraint('fk_activated_strategies_leader_account', 'activated_strategies', type_='foreignkey')
    op.drop_constraint('fk_activated_strategies_account_id', 'activated_strategies', type_='foreignkey')

    # Restore original webhook foreign key
    op.create_foreign_key('activated_strategies_webhook_id_fkey', 
                         'activated_strategies', 'webhooks',
                         ['webhook_id'], ['token'], 
                         ondelete='CASCADE')

    # Revert column modifications
    op.alter_column('webhooks', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('webhooks', 'token',
               existing_type=sa.VARCHAR(length=64),
               nullable=True)
    
    # Drop unique constraint and revert broker_accounts changes
    op.drop_constraint('uq_broker_accounts_account_id', 'broker_accounts', type_='unique')
    op.alter_column('broker_accounts', 'account_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=True)
    
    # Finally revert activated_strategies account_id
    op.alter_column('activated_strategies', 'account_id',
               existing_type=sa.String(),
               type_=sa.INTEGER(),
               existing_nullable=True)
