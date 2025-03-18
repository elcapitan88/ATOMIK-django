"""add_password_reset_table

Revision ID: 4a29f9366e8f
Revises: 88aa2fda8b74
Create Date: 2025-03-13 16:39:57.676623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a29f9366e8f'
down_revision: Union[str, None] = '88aa2fda8b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create password_resets table
    op.create_table(
        'password_resets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index(op.f('ix_password_resets_id'), 'password_resets', ['id'], unique=False)
    op.create_index(op.f('ix_password_resets_token'), 'password_resets', ['token'], unique=True)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_password_resets_token'), table_name='password_resets')
    op.drop_index(op.f('ix_password_resets_id'), table_name='password_resets')
    
    # Drop table
    op.drop_table('password_resets')