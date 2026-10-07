"""users.is_admin

Revision ID: 0011
Revises: 0012
Create Date: 2026-10-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspect = sa.inspect(bind)
    columns = {c["name"] for c in inspect.get_columns("users")}
    if "is_admin" not in columns:
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    pass
