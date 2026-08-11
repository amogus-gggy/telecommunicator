"""group e2ee: rooms.key_epoch + sender_key_distributions table

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

    # --- rooms.key_epoch (membership generation for sender-key rotation) ---
    columns = {c["name"] for c in inspect.get_columns("rooms")}
    if "key_epoch" not in columns:
        op.add_column(
            "rooms",
            sa.Column(
                "key_epoch", sa.Integer(), nullable=False, server_default="1"
            ),
        )

    # --- sender_key_distributions (pairwise-encrypted group chain bundles) ---
    if not inspect.has_table("sender_key_distributions"):
        op.create_table(
            "sender_key_distributions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("room_id", sa.Integer(), nullable=False),
            sa.Column("sender_id", sa.Integer(), nullable=False),
            sa.Column("recipient_id", sa.Integer(), nullable=False),
            sa.Column("chain_id", sa.String(64), nullable=False),
            sa.Column("key_epoch", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("encrypted_blob", sa.LargeBinary(), nullable=False),
            sa.Column("signature", sa.LargeBinary(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["recipient_id"], ["users.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "uq_sender_key_bundle",
            "sender_key_distributions",
            ["room_id", "sender_id", "recipient_id", "chain_id"],
            unique=True,
        )
        op.create_index(
            "ix_sender_key_recipient_room",
            "sender_key_distributions",
            ["recipient_id", "room_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)

    if inspect.has_table("sender_key_distributions"):
        op.drop_index(
            "ix_sender_key_recipient_room", table_name="sender_key_distributions"
        )
        op.drop_index("uq_sender_key_bundle", table_name="sender_key_distributions")
        op.drop_table("sender_key_distributions")

    columns = {c["name"] for c in inspect.get_columns("rooms")}
    if "key_epoch" in columns:
        op.drop_column("rooms", "key_epoch")
