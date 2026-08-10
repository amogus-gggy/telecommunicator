from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RemoteRoomLink(Base):
    """Maps a locally-hosted room to its mirror/link room on a foreign server.

    When a federated (hosted) room has members on another homeserver, this row
    records the PK of the mirror room on that server so messages and
    membership changes can be relayed to it.
    """

    __tablename__ = "remote_room_links"

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True
    )
    server_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    remote_room_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())