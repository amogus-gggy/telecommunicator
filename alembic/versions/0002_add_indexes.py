"""add performance indexes

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Speeds up message history queries (most frequent query)
    op.create_index("ix_messages_room_id", "messages", ["room_id"])
    # Speeds up cursor-based pagination
    op.create_index("ix_messages_room_id_id", "messages", ["room_id", "id"])
    # Speeds up "my rooms" query
    op.create_index("ix_room_members_user_id", "room_members", ["user_id"])
    # Speeds up membership existence checks
    op.create_index("ix_room_members_room_user", "room_members", ["room_id", "user_id"])
    # Speeds up owner-based permission checks
    op.create_index("ix_rooms_owner_id", "rooms", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_rooms_owner_id", "rooms")
    op.drop_index("ix_room_members_room_user", "room_members")
    op.drop_index("ix_room_members_user_id", "room_members")
    op.drop_index("ix_messages_room_id_id", "messages")
    op.drop_index("ix_messages_room_id", "messages")
