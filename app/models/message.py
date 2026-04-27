from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.user import User


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    # E2EE fields
    encrypted_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    sender_encrypted_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary(64), nullable=True)
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    files: Mapped[list["File"]] = relationship("File", back_populates="message")
    recipient: Mapped["User | None"] = relationship(
        "User", foreign_keys=[recipient_id]
    )
