"""Add room_type field

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite doesn't support dropping constraints directly, so we need to recreate the table
    
    # Create new table with room_type and without unique constraint on name
    op.create_table('rooms_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('room_type', sa.String(), nullable=False, server_default='public'),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('is_private', sa.Boolean(), nullable=False, default=False),
        sa.Column('allow_member_invite', sa.Boolean(), nullable=False, default=False),
        sa.Column('read_only', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data from old table to new table
    op.execute("""
        INSERT INTO rooms_new (id, name, room_type, owner_id, is_private, allow_member_invite, read_only, created_at)
        SELECT id, name, 'public', owner_id, is_private, allow_member_invite, read_only, created_at
        FROM rooms
    """)
    
    # Drop old table
    op.drop_table('rooms')
    
    # Rename new table to original name
    op.rename_table('rooms_new', 'rooms')
    
    # Recreate index
    op.create_index('ix_rooms_owner_id', 'rooms', ['owner_id'])


def downgrade() -> None:
    # Recreate table with unique constraint and without room_type
    op.create_table('rooms_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('is_private', sa.Boolean(), nullable=False, default=False),
        sa.Column('allow_member_invite', sa.Boolean(), nullable=False, default=False),
        sa.Column('read_only', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Copy data back (excluding room_type)
    op.execute("""
        INSERT INTO rooms_old (id, name, owner_id, is_private, allow_member_invite, read_only, created_at)
        SELECT id, name, owner_id, is_private, allow_member_invite, read_only, created_at
        FROM rooms
    """)
    
    # Drop current table
    op.drop_table('rooms')
    
    # Rename old table back
    op.rename_table('rooms_old', 'rooms')
    
    # Recreate index
    op.create_index('ix_rooms_owner_id', 'rooms', ['owner_id'])