from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, relationship
from typing import Optional # Import Optional
from app.db.base import Base

class File(Base):
    __tablename__ = "room_files"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id"))
    room_id = Column(Integer, ForeignKey("rooms.id"))
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True) # Added message_id
    created_at = Column(DateTime, default=func.now(), nullable=False)

    # Relationships
    message: Mapped[Optional["Message"]] = relationship("Message", back_populates="files") # Added message relationship