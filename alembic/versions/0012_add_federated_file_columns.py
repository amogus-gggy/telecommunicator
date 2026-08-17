"""add federated file origin columns

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "room_files",
        sa.Column("origin_server_name", sa.String(), nullable=True),
    )
    op.add_column(
        "room_files",
        sa.Column("origin_file_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("room_files", "origin_file_id")
    op.drop_column("room_files", "origin_server_name")
