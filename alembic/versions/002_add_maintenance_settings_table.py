"""add_maintenance_settings_table

Revision ID: 002_add_maintenance_settings
Revises: d4d300d41aa7
Create Date: 2025-07-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_add_maintenance_settings'
down_revision: Union[str, None] = 'd4d300d41aa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create maintenance_settings table
    op.create_table('maintenance_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, default=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create index on created_by for faster lookups
    op.create_index(op.f('ix_maintenance_settings_created_by'), 'maintenance_settings', ['created_by'], unique=False)
    
    # Create index on updated_at for ordering by latest
    op.create_index(op.f('ix_maintenance_settings_updated_at'), 'maintenance_settings', ['updated_at'], unique=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_maintenance_settings_updated_at'), table_name='maintenance_settings')
    op.drop_index(op.f('ix_maintenance_settings_created_by'), table_name='maintenance_settings')
    
    # Drop table
    op.drop_table('maintenance_settings')