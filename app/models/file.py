from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, relationship
from typing import Optional, TYPE_CHECKING
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.message import Message

class File(Base):
    __tablename__ = "room_files"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id"))
    room_id = Column(Integer, ForeignKey("rooms.id"))
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    # E2EE fields
    is_encrypted = Column(Boolean, nullable=False, default=False)
    key_blob = Column(Text, nullable=True)           # base64 JSON — recipient key blob
    key_sender_blob = Column(Text, nullable=True)    # base64 JSON — sender key blob
    key_signature = Column(Text, nullable=True)      # base64 Ed25519 signature

    message: Mapped[Optional["Message"]] = relationship("Message", back_populates="files")