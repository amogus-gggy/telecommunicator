from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SenderKeyDistribution(Base):
    """A sender-key chain shipped from one room member to another.

    The row only ever holds *ciphertext*: the payload is the sender's chain key
    encrypted with the pairwise Double Ratchet session between sender and
    recipient, so the server can route group key material without ever being
    able to read a group message.
    """

    __tablename__ = "sender_key_distributions"
    __table_args__ = (
        # One bundle per (room, sender, recipient, chain) — resending a bundle
        # (e.g. after a client reinstall) must update, never duplicate.
        Index(
            "uq_sender_key_bundle",
            "room_id",
            "sender_id",
            "recipient_id",
            "chain_id",
            unique=True,
        ),
        Index("ix_sender_key_recipient_room", "recipient_id", "room_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Opaque identifier of the sender chain this bundle carries.
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Membership generation the chain belongs to (see Room.key_epoch).
    key_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Pairwise-ratchet ciphertext + Ed25519 signature over it.
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)
