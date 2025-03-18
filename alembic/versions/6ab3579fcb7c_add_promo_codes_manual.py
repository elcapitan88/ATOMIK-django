"""add_promo_codes_manual

Revision ID: 6ab3579fcb7c
Revises: 5abc123def45
Create Date: 2025-03-17 14:33:39.672063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ab3579fcb7c'
down_revision: Union[str, None] = '5abc123def45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create promo_codes table
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
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_promo_codes_created_by', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    
    # Create indexes
    op.create_index(op.f('ix_promo_codes_id'), 'promo_codes', ['id'], unique=False)
    op.create_index(op.f('ix_promo_codes_code'), 'promo_codes', ['code'], unique=True)
    
    # Add promo_code_id to users table
    op.add_column('users', sa.Column('promo_code_id', sa.Integer(), nullable=True))
    
    # Add foreign key constraint after both tables exist
    op.create_foreign_key(
        'fk_users_promo_code_id',
        'users', 'promo_codes',
        ['promo_code_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Drop foreign key first
    op.drop_constraint('fk_users_promo_code_id', 'users', type_='foreignkey')
    
    # Remove promo_code_id column from users
    op.drop_column('users', 'promo_code_id')
    
    # Drop foreign key from promo_codes to users
    op.drop_constraint('fk_promo_codes_created_by', 'promo_codes', type_='foreignkey')
    
    # Drop indexes
    op.drop_index(op.f('ix_promo_codes_code'), table_name='promo_codes')
    op.drop_index(op.f('ix_promo_codes_id'), table_name='promo_codes')
    
    # Drop promo_codes table
    op.drop_table('promo_codes')