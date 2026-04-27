"""add sender_encrypted_blob to messages

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('messages', sa.Column('sender_encrypted_blob', sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column('messages', 'sender_encrypted_blob')
