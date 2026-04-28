"""add file e2ee fields

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "room_files",
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("room_files", sa.Column("key_blob", sa.Text(), nullable=True))
    op.add_column("room_files", sa.Column("key_sender_blob", sa.Text(), nullable=True))
    op.add_column("room_files", sa.Column("key_signature", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("room_files", "key_signature")
    op.drop_column("room_files", "key_sender_blob")
    op.drop_column("room_files", "key_blob")
    op.drop_column("room_files", "is_encrypted")
