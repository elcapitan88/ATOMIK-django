"""add_promo_codes_system

Revision ID: 5abc123def45
Revises: 3faac94c8667
Create Date: 2025-03-17 09:15:32.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5abc123def45'
down_revision: Union[str, None] = '3faac94c8667'  # This points to your latest migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Create promo_codes table
    op.create_table(
        'promo_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(16), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('current_uses', sa.Integer(), server_default='0', nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    
    # Create indexes
    op.create_index(op.f('ix_promo_codes_id'), 'promo_codes', ['id'], unique=False)
    op.create_index(op.f('ix_promo_codes_code'), 'promo_codes', ['code'], unique=True)
    
    # Step 2: Add foreign key from created_by to users table
    op.create_foreign_key(
        'fk_promo_codes_created_by',
        'promo_codes', 'users',
        ['created_by'], ['id'],
        ondelete='SET NULL'
    )
    
    # Step 3: Add promo_code_id to users table
    op.add_column('users', sa.Column('promo_code_id', sa.Integer(), nullable=True))
    
    # Step 4: Add foreign key from users.promo_code_id to promo_codes.id
    op.create_foreign_key(
        'fk_users_promo_code_id',
        'users', 'promo_codes',
        ['promo_code_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Step 1: Remove foreign keys
    op.drop_constraint('fk_users_promo_code_id', 'users', type_='foreignkey')
    op.drop_constraint('fk_promo_codes_created_by', 'promo_codes', type_='foreignkey')
    
    # Step 2: Remove the promo_code_id column from users
    op.drop_column('users', 'promo_code_id')
    
    # Step 3: Drop indexes
    op.drop_index(op.f('ix_promo_codes_code'), table_name='promo_codes')
    op.drop_index(op.f('ix_promo_codes_id'), table_name='promo_codes')
    
    # Step 4: Drop the promo_codes table
    op.drop_table('promo_codes')