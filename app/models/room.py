from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.settings import SERVER_NAME


class RoomType(str, Enum):
    PERSONAL = "personal"  # Личный чат между двумя пользователями
    GROUP = "group"  # Групповой чат
    PUBLIC = "public"  # Публичный канал


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    room_type: Mapped[RoomType] = mapped_column(default=RoomType.PUBLIC)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_private: Mapped[bool] = mapped_column(default=False)
    allow_member_invite: Mapped[bool] = mapped_column(default=False)
    read_only: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    # --- Group E2EE (sender keys) ---
    # Membership generation counter. Bumped on every join/invite/leave/removal
    # so clients know their sender chain is stale and must be rotated before
    # the next message (a removed member must not be able to read on).
    key_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # --- Federation fields ---
    # Name of the server that hosts the canonical copy of this room. For rooms
    # created locally it equals SERVER_NAME.
    server_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default=SERVER_NAME
    )
    # PK of the room on its hosting server (None for locally-hosted rooms).
    remote_room_id: Mapped[int | None] = mapped_column(Integer, nullable=True)