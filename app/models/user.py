from datetime import datetime

from sqlalchemy import LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    # E2EE fields (Requirements 1.4, 1.5, 14.1, 14.2)
    identity_pub_ed25519: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    identity_pub_x25519: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)

    # Key backup fields (Requirements 2.6)
    encrypted_backup: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    backup_version: Mapped[int] = mapped_column(default=1, nullable=False, server_default="1")
