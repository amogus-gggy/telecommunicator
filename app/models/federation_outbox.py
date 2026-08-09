from datetime import datetime

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FederationOutbox(Base):
    """A not-yet-delivered federated room message.

    The sending server writes one row per (event, target mirror) *before* it
    attempts delivery and deletes it on success. Rows that survive a crash or a
    permanently-unreachable peer are drained by ``flush_pending_relays`` as well
    as by a periodic background task, so a lost federation message is never
    dropped silently.
    """

    __tablename__ = "federation_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Local room the event belongs to (hosted room or local mirror).
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Remote mirror's local room PK on the target server (used as the URL path).
    remote_room_id: Mapped[int] = mapped_column(Integer, nullable=False)
    server_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Source-of-truth dedup key, so a redelivery is ignored by the receiver.
    event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sender_member: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())