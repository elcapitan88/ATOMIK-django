"""add_digital_ocean_columns

Revision ID: 33b23b51a89f
Revises: 0872a507d627
Create Date: 2025-04-02 17:21:09.713444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '33b23b51a89f'
down_revision: Union[str, None] = '0872a507d627'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add only the Digital Ocean columns
    op.add_column('broker_credentials', sa.Column('do_droplet_id', sa.Integer(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_droplet_name', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_server_status', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_ip_address', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_region', sa.String(), nullable=True))
    op.add_column('broker_credentials', sa.Column('do_last_status_check', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove the Digital Ocean columns in reverse order
    op.drop_column('broker_credentials', 'do_last_status_check')
    op.drop_column('broker_credentials', 'do_region')
    op.drop_column('broker_credentials', 'do_ip_address')
    op.drop_column('broker_credentials', 'do_server_status')
    op.drop_column('broker_credentials', 'do_droplet_name')
    op.drop_column('broker_credentials', 'do_droplet_id')