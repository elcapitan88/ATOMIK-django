"""modify_follower_accounts_reference

Revision ID: 183b34d3df5c
Revises: a4365b1409fa
Create Date: 2025-02-02 19:52:03.621468

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '183b34d3df5c'
down_revision: Union[str, None] = 'a4365b1409fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create a temporary table to store the data
    op.execute('CREATE TABLE temp_follower_quantities AS SELECT * FROM strategy_follower_quantities')
    
    # Drop the original table
    op.drop_table('strategy_follower_quantities')
    
    # Create the new table with correct column types
    op.create_table('strategy_follower_quantities',
        sa.Column('strategy_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['strategy_id'], ['activated_strategies.id'], ),
        sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.account_id'], ),
        sa.UniqueConstraint('strategy_id', 'account_id', name='unique_strategy_follower')
    )
    
    # Copy data from temp table after joining with broker_accounts to get account_id
    op.execute('''
        INSERT INTO strategy_follower_quantities (strategy_id, account_id, quantity)
        SELECT t.strategy_id, ba.account_id, t.quantity 
        FROM temp_follower_quantities t
        JOIN broker_accounts ba ON ba.id = t.account_id::integer
    ''')
    
    # Drop the temporary table
    op.execute('DROP TABLE temp_follower_quantities')


def downgrade() -> None:
    # Similar process but in reverse
    op.execute('CREATE TABLE temp_follower_quantities AS SELECT * FROM strategy_follower_quantities')
    
    op.drop_table('strategy_follower_quantities')
    
    op.create_table('strategy_follower_quantities',
        sa.Column('strategy_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['strategy_id'], ['activated_strategies.id'], ),
        sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ),
        sa.UniqueConstraint('strategy_id', 'account_id', name='unique_strategy_follower')
    )
    
    op.execute('''
        INSERT INTO strategy_follower_quantities (strategy_id, account_id, quantity)
        SELECT t.strategy_id, ba.id, t.quantity 
        FROM temp_follower_quantities t
        JOIN broker_accounts ba ON ba.account_id = t.account_id
    ''')
    
    op.execute('DROP TABLE temp_follower_quantities')