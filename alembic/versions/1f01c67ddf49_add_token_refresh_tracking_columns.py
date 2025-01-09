"""add_token_refresh_tracking_columns

Revision ID: 1f01c67ddf49
Revises: 88e9841690f6
Create Date: 2024-01-07 10:20:24.483675

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1f01c67ddf49'
down_revision = '88e9841690f6'
branch_labels = None
depends_on = None

def upgrade():
    # Create new table with updated schema
    op.create_table(
        'broker_credentials_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('broker_id', sa.String(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('credential_type', sa.String(length=20), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('refresh_token', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.current_timestamp()),
        sa.Column('refresh_fail_count', sa.Integer(), default=0),
        sa.Column('last_refresh_attempt', sa.DateTime(), nullable=True),
        sa.Column('last_refresh_error', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Copy data from old table to new table
    op.execute('''
        INSERT INTO broker_credentials_new (
            id, broker_id, account_id, credential_type, access_token, 
            refresh_token, expires_at, is_valid, created_at
        )
        SELECT id, broker_id, account_id, credential_type, access_token,
               refresh_token, expires_at, is_valid, created_at
        FROM broker_credentials
    ''')

    # Drop old table
    op.drop_table('broker_credentials')

    # Rename new table to original name
    op.rename_table('broker_credentials_new', 'broker_credentials')

    # Create index on the new table
    op.create_index(op.f('ix_broker_credentials_id'), 'broker_credentials', ['id'], unique=False)

def downgrade():
    # Create the original table structure
    op.create_table(
        'broker_credentials_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('broker_id', sa.String(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('credential_type', sa.String(length=20), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Copy data back
    op.execute('''
        INSERT INTO broker_credentials_old (
            id, broker_id, account_id, credential_type, access_token,
            refresh_token, expires_at, is_valid, created_at
        )
        SELECT id, broker_id, account_id, credential_type, access_token,
               refresh_token, expires_at, is_valid, created_at
        FROM broker_credentials
    ''')

    # Drop new table
    op.drop_table('broker_credentials')

    # Rename old table back to original name
    op.rename_table('broker_credentials_old', 'broker_credentials')

    # Recreate index
    op.create_index(op.f('ix_broker_credentials_id'), 'broker_credentials', ['id'], unique=False)