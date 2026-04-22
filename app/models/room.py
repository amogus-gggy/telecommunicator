from datetime import datetime
from enum import Enum

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoomType(str, Enum):
    PERSONAL = "personal"  # Личный чат между двумя пользователями
    GROUP = "group"        # Групповой чат
    PUBLIC = "public"      # Публичный канал


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
