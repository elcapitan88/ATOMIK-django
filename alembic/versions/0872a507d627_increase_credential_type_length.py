"""increase_credential_type_length

Revision ID: 0872a507d627
Revises: cf4213541fe2
Create Date: 2025-03-30 18:32:32.182564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0872a507d627'
down_revision: Union[str, None] = 'cf4213541fe2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column('broker_credentials', 'credential_type', 
                   existing_type=sa.VARCHAR(20),
                   type_=sa.VARCHAR(30))

def downgrade():
    op.alter_column('broker_credentials', 'credential_type', 
                   existing_type=sa.VARCHAR(30),
                   type_=sa.VARCHAR(20))