from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SenderKey(Base):
    """One sender-key distribution blob, encrypted for a single recipient.

    The server never sees the chain key: ``blob`` is an opaque base64 payload
    produced by the sender's client, wrapped under the recipient's identity
    X25519 key. Rotating replaces the (room, sender, recipient) row in place.
    """

    __tablename__ = "sender_keys"
    __table_args__ = (
        UniqueConstraint(
            "room_id", "sender_id", "recipient_id", name="uq_sender_keys_room_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blob: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
