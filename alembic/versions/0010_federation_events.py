"""federation: message event_id (dedup), federation_outbox table

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-09 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)

    # --- messages.event_id (dedup key) ---
    columns = {c["name"] for c in inspect.get_columns("messages")}
    if "event_id" not in columns:
        op.add_column(
            "messages",
            sa.Column("event_id", sa.String(32), nullable=True),
        )
    indexes = {ix["name"] for ix in inspect.get_indexes("messages")}
    if "ix_messages_event_id" not in indexes:
        op.create_index("ix_messages_event_id", "messages", ["event_id"])
    if "uq_messages_room_event" not in indexes:
        # SQLite cannot add a UNIQUE table constraint in place, so the constraint
        # is expressed as a unique index (application dedup is layered on top).
        op.create_index(
            "uq_messages_room_event", "messages", ["room_id", "event_id"], unique=True
        )

    # --- federation_outbox (durable relay queue) ---
    if not inspect.has_table("federation_outbox"):
        op.create_table(
            "federation_outbox",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("room_id", sa.Integer(), nullable=False),
            sa.Column("remote_room_id", sa.Integer(), nullable=False),
            sa.Column("server_name", sa.String(255), nullable=False),
            sa.Column("event_id", sa.String(32), nullable=True),
            sa.Column("sender_member", sa.JSON(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_federation_outbox_room_id", "federation_outbox", ["room_id"]
        )
        op.create_index(
            "ix_federation_outbox_server_name",
            "federation_outbox",
            ["server_name"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)
    if inspect.has_table("federation_outbox"):
        op.drop_index(
            "ix_federation_outbox_server_name", table_name="federation_outbox"
        )
        op.drop_index("ix_federation_outbox_room_id", table_name="federation_outbox")
        op.drop_table("federation_outbox")

    indexes = {ix["name"] for ix in inspect.get_indexes("messages")}
    if "uq_messages_room_event" in indexes:
        op.drop_index("uq_messages_room_event", table_name="messages")
    if "ix_messages_event_id" in indexes:
        op.drop_index("ix_messages_event_id", table_name="messages")
    columns = {c["name"] for c in inspect.get_columns("messages")}
    if "event_id" in columns:
        op.drop_column("messages", "event_id")