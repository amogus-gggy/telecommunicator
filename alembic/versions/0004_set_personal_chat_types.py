"""Set room_type for existing personal chats

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set room_type='personal' for rooms with exactly 2 members
    # This identifies personal chats (1-on-1 conversations)
    op.execute("""
        UPDATE rooms
        SET room_type = 'personal'
        WHERE id IN (
            SELECT room_id
            FROM room_members
            GROUP BY room_id
            HAVING COUNT(*) = 2
        )
        AND (room_type IS NULL OR room_type = 'public')
    """)


def downgrade() -> None:
    # Revert personal chats back to 'public' type
    op.execute("""
        UPDATE rooms
        SET room_type = 'public'
        WHERE room_type = 'personal'
    """)
