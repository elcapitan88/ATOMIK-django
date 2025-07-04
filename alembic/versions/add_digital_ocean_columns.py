"""add digital ocean columns and custom_data

Revision ID: add_digital_ocean_columns
Revises: d4d300d41aa7
Create Date: 2025-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_digital_ocean_columns'
down_revision: Union[str, None] = 'd4d300d41aa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add custom_data column if it doesn't exist
    op.add_column('broker_credentials', sa.Column('custom_data', sa.Text(), nullable=True))
    
    # Add Digital Ocean columns
    op.add_column('broker_credentials', sa.Column('do_droplet_id', sa.Integer(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_droplet_name', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_server_status', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_ip_address', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_region', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_last_status_check', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove the Digital Ocean columns
    op.drop_column('broker_credentials', 'do_last_status_check')
    op.drop_column('broker_credentials', 'do_region')
    op.drop_column('broker_credentials', 'do_ip_address')
    op.drop_column('broker_credentials', 'do_server_status')
    op.drop_column('broker_credentials', 'do_droplet_name')
    op.drop_column('broker_credentials', 'do_droplet_id')
    op.drop_column('broker_credentials', 'custom_data')