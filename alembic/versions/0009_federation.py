"""federation: servers table, user/room federation fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-07 00:00:00.000000

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.settings import SERVER_NAME as _LOCAL

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_new_table() -> sa.Table:
    return op.create_table(
        "users_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=False, server_default=_LOCAL),
        sa.Column("is_remote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("identity_pub_ed25519", sa.LargeBinary(32), nullable=True),
        sa.Column("identity_pub_x25519", sa.LargeBinary(32), nullable=True),
        sa.Column("encrypted_backup", sa.LargeBinary(), nullable=True),
        sa.Column(
            "backup_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint(
            "username", "server_name", name="uq_users_username_server_name"
        ),
    )


def upgrade() -> None:
    # --- servers table ---
    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_key", sa.LargeBinary(32), nullable=True),
        sa.Column("private_key", sa.LargeBinary(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_name"),
    )

    # --- users: drop unique(username), add server_name/is_remote, composite unique ---
    # SQLite cannot drop a unique constraint in place, so we recreate the table
    # (mirroring the rooms table migration) and backfill the data.
    op.create_table(
        "users_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=False, server_default=_LOCAL),
        sa.Column("is_remote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("identity_pub_ed25519", sa.LargeBinary(32), nullable=True),
        sa.Column("identity_pub_x25519", sa.LargeBinary(32), nullable=True),
        sa.Column("encrypted_backup", sa.LargeBinary(), nullable=True),
        sa.Column(
            "backup_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint(
            "username", "server_name", name="uq_users_username_server_name"
        ),
    )

    op.execute(
        """
        INSERT INTO users_new (
            id, username, server_name, is_remote, email, display_name,
            hashed_password, created_at,
            identity_pub_ed25519, identity_pub_x25519,
            encrypted_backup, backup_version
        )
        SELECT
            id, username, '{local}', 0, email, display_name,
            hashed_password, created_at,
            identity_pub_ed25519, identity_pub_x25519,
            encrypted_backup, backup_version
        FROM users
        """.format(local=_LOCAL)
    )

    op.drop_table("users")
    op.rename_table("users_new", "users")
    op.create_index("ix_users_server_name", "users", ["server_name"])

    # --- rooms: federation fields ---
    op.add_column(
        "rooms",
        sa.Column("server_name", sa.String(255), nullable=False, server_default=_LOCAL),
    )
    op.add_column(
        "rooms", sa.Column("remote_room_id", sa.Integer(), nullable=True)
    )

    # --- remote room mirrors ---
    op.create_table(
        "remote_room_links",
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("remote_room_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("room_id", "server_name"),
    )


def downgrade() -> None:
    op.drop_table("remote_room_links")

    op.drop_column("rooms", "remote_room_id")
    op.drop_column("rooms", "server_name")

    op.drop_index("ix_users_server_name", table_name="users")

    # Restore the old global-unique users table.
    op.create_table(
        "users_orig",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("identity_pub_ed25519", sa.LargeBinary(32), nullable=True),
        sa.Column("identity_pub_x25519", sa.LargeBinary(32), nullable=True),
        sa.Column("encrypted_backup", sa.LargeBinary(), nullable=True),
        sa.Column(
            "backup_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )

    op.execute(
        """
        INSERT INTO users_orig (
            id, username, email, display_name, hashed_password, created_at,
            identity_pub_ed25519, identity_pub_x25519,
            encrypted_backup, backup_version
        )
        SELECT
            id, username, email, display_name, hashed_password, created_at,
            identity_pub_ed25519, identity_pub_x25519,
            encrypted_backup, backup_version
        FROM users
        """
    )

    op.drop_table("users")
    op.rename_table("users_orig", "users")

    op.drop_table("servers")