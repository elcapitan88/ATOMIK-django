"""add_strategy_follower_quantities

Revision ID: 977554242bd9
Revises: <automatically_generated_id>
Create Date: 2025-01-26 15:00:35.130474
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '977554242bd9'
down_revision: Union[str, None] = '<automatically_generated_id>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # First check if the table exists
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Only create the table if it doesn't exist
    if 'strategy_follower_quantities' not in inspector.get_table_names():
        op.create_table(
            'strategy_follower_quantities',
            sa.Column('strategy_id', sa.Integer(), nullable=False),
            sa.Column('account_id', sa.Integer(), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ['strategy_id'], 
                ['activated_strategies.id'], 
                ondelete='CASCADE',
                name='strategy_follower_quantities_strategy_id_fkey'
            ),
            sa.ForeignKeyConstraint(
                ['account_id'], 
                ['broker_accounts.id'], 
                ondelete='CASCADE',
                name='strategy_follower_quantities_account_id_fkey'
            ),
            sa.UniqueConstraint('strategy_id', 'account_id', name='unique_strategy_follower')
        )
        
        # Create index
        op.create_index(
            'ix_strategy_follower_quantities_strategy_id',
            'strategy_follower_quantities',
            ['strategy_id']
        )

    # Handle the old tables/columns if they exist
    if 'strategy_followers' in inspector.get_table_names():
        op.drop_table('strategy_followers')
    
    # Check if column exists before trying to drop it
    if 'follower_quantity' in [c['name'] for c in inspector.get_columns('activated_strategies')]:
        op.drop_column('activated_strategies', 'follower_quantity')

    # If we have a strategy_followers table, migrate its data
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    if 'strategy_followers' in inspector.get_table_names():
        # Get existing relationships
        followers_data = connection.execute(
            text('SELECT strategy_id, account_id FROM strategy_followers')
        ).fetchall()
        
        # Get follower quantities if the column exists
        if 'follower_quantity' in inspector.get_columns('activated_strategies'):
            quantities = connection.execute(
                text('SELECT id, follower_quantity FROM activated_strategies WHERE follower_quantity IS NOT NULL')
            ).fetchall()
            quantities_dict = {row[0]: row[1] for row in quantities}
            
            # Migrate data
            for strategy_id, account_id in followers_data:
                quantity = quantities_dict.get(strategy_id, 1)  # Default to 1 if no quantity found
                connection.execute(
                    text(f'INSERT INTO strategy_follower_quantities (strategy_id, account_id, quantity) VALUES (:sid, :aid, :qty)'),
                    {"sid": strategy_id, "aid": account_id, "qty": quantity}
                )
        
        # Drop old structures
        op.drop_table('strategy_followers')
        
    # Drop the old follower_quantity column if it exists
    if 'follower_quantity' in inspector.get_columns('activated_strategies'):
        op.drop_column('activated_strategies', 'follower_quantity')

def downgrade() -> None:
    # Create old structures
    op.create_table(
        'strategy_followers',
        sa.Column('strategy_id', sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('account_id', sa.INTEGER(), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(
            ['account_id'], 
            ['broker_accounts.id'], 
            name='strategy_followers_account_id_fkey'
        ),
        sa.ForeignKeyConstraint(
            ['strategy_id'], 
            ['activated_strategies.id'], 
            name='strategy_followers_strategy_id_fkey'
        )
    )
    
    op.add_column(
        'activated_strategies', 
        sa.Column('follower_quantity', sa.INTEGER(), autoincrement=False, nullable=True)
    )
    
    # Migrate data back if the new table exists
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    if 'strategy_follower_quantities' in inspector.get_table_names():
        # Get data from the new table
        followers_data = connection.execute(
            text('SELECT strategy_id, account_id, quantity FROM strategy_follower_quantities')
        ).fetchall()
        
        # Migrate data back to old structure
        for strategy_id, account_id, quantity in followers_data:
            connection.execute(
                text('INSERT INTO strategy_followers (strategy_id, account_id) VALUES (:sid, :aid)'),
                {"sid": strategy_id, "aid": account_id}
            )
            connection.execute(
                text('UPDATE activated_strategies SET follower_quantity = :qty WHERE id = :sid'),
                {"qty": quantity, "sid": strategy_id}
            )
    
    # Drop new structures
    op.drop_index('ix_strategy_follower_quantities_strategy_id')
    op.drop_table('strategy_follower_quantities')