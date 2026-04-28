"""add e2ee fields

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add E2EE identity key fields to users
    op.add_column(
        "users", sa.Column("identity_pub_ed25519", sa.LargeBinary(32), nullable=True)
    )
    op.add_column(
        "users", sa.Column("identity_pub_x25519", sa.LargeBinary(32), nullable=True)
    )

    # Add key backup fields to users
    op.add_column(
        "users", sa.Column("encrypted_backup", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("backup_version", sa.Integer(), nullable=False, server_default="1"),
    )

    # Add E2EE fields to messages
    op.add_column(
        "messages", sa.Column("encrypted_blob", sa.LargeBinary(), nullable=True)
    )
    op.add_column("messages", sa.Column("signature", sa.LargeBinary(64), nullable=True))
    # Note: SQLite does not support adding FK constraints via ALTER TABLE.
    # recipient_id is added as a plain integer; the FK relationship is enforced at the ORM level.
    op.add_column("messages", sa.Column("recipient_id", sa.Integer(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("messages", sa.Column("delivered_at", sa.DateTime(), nullable=True))

    # Make body nullable in messages using batch mode (required for SQLite)
    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column("body", existing_type=sa.Text(), nullable=True)

    # Add index on messages.recipient_id
    op.create_index("ix_messages_recipient_id", "messages", ["recipient_id"])


def downgrade():
    op.drop_index("ix_messages_recipient_id", table_name="messages")

    op.drop_column("messages", "delivered_at")
    op.drop_column("messages", "is_encrypted")
    op.drop_column("messages", "recipient_id")
    op.drop_column("messages", "signature")
    op.drop_column("messages", "encrypted_blob")

    op.drop_column("users", "backup_version")
    op.drop_column("users", "encrypted_backup")
    op.drop_column("users", "identity_pub_x25519")
    op.drop_column("users", "identity_pub_ed25519")
