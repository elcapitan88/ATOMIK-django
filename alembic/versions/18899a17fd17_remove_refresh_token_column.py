"""remove refresh token column

Revision ID: [alembic will generate this]
Revises: 1f01c67ddf49  # This should be your current migration ID
Create Date: 2024-01-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '[alembic will generate this]'
down_revision = '1f01c67ddf49'  # Your current migration ID
branch_labels = None
depends_on = None

def upgrade():
    # Create new table without refresh_token column
    op.create_table(
        'broker_credentials_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('broker_id', sa.String(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('credential_type', sa.String(length=20), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
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

    # Copy all data except refresh_token
    op.execute('''
        INSERT INTO broker_credentials_new (
            id, broker_id, account_id, credential_type, access_token,
            expires_at, is_valid, created_at, updated_at, refresh_fail_count,
            last_refresh_attempt, last_refresh_error
        )
        SELECT id, broker_id, account_id, credential_type, access_token,
               expires_at, is_valid, created_at, updated_at, refresh_fail_count,
               last_refresh_attempt, last_refresh_error
        FROM broker_credentials
    ''')

    # Drop old table
    op.drop_table('broker_credentials')

    # Rename new table to original name
    op.rename_table('broker_credentials_new', 'broker_credentials')

    # Create index
    op.create_index(op.f('ix_broker_credentials_id'), 'broker_credentials', ['id'], unique=False)

def downgrade():
    # Create table with refresh_token column
    op.create_table(
        'broker_credentials_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('broker_id', sa.String(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('credential_type', sa.String(length=20), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('refresh_token', sa.String(), nullable=True),  # Add back refresh_token
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

    # Copy data back, setting refresh_token to NULL
    op.execute('''
        INSERT INTO broker_credentials_old (
            id, broker_id, account_id, credential_type, access_token,
            refresh_token, expires_at, is_valid, created_at, updated_at,
            refresh_fail_count, last_refresh_attempt, last_refresh_error
        )
        SELECT id, broker_id, account_id, credential_type, access_token,
               NULL, expires_at, is_valid, created_at, updated_at,
               refresh_fail_count, last_refresh_attempt, last_refresh_error
        FROM broker_credentials
    ''')

    # Drop new table
    op.drop_table('broker_credentials')

    # Rename old table back
    op.rename_table('broker_credentials_old', 'broker_credentials')

    # Recreate index
    op.create_index(op.f('ix_broker_credentials_id'), 'broker_credentials', ['id'], unique=False)