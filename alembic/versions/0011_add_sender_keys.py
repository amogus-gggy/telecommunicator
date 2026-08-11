"""group e2ee: sender_keys distribution table

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)

    if not inspect.has_table("sender_keys"):
        op.create_table(
            "sender_keys",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("room_id", sa.Integer(), nullable=False),
            sa.Column("sender_id", sa.Integer(), nullable=False),
            sa.Column("recipient_id", sa.Integer(), nullable=False),
            sa.Column(
                "generation", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("blob", sa.Text(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["recipient_id"], ["users.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "room_id", "sender_id", "recipient_id",
                name="uq_sender_keys_room_pair",
            ),
        )
        op.create_index("ix_sender_keys_room_id", "sender_keys", ["room_id"])
        op.create_index("ix_sender_keys_sender_id", "sender_keys", ["sender_id"])
        op.create_index(
            "ix_sender_keys_recipient_id", "sender_keys", ["recipient_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)
    if inspect.has_table("sender_keys"):
        op.drop_index("ix_sender_keys_recipient_id", table_name="sender_keys")
        op.drop_index("ix_sender_keys_sender_id", table_name="sender_keys")
        op.drop_index("ix_sender_keys_room_id", table_name="sender_keys")
        op.drop_table("sender_keys")
