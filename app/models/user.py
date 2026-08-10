from datetime import datetime

from sqlalchemy import Boolean, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.settings import SERVER_NAME


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "username", "server_name", name="uq_users_username_server_name"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # Homeserver that hosts this account. For local users it is SERVER_NAME.
    server_name: Mapped[str] = mapped_column(String(255), nullable=False, default=SERVER_NAME)
    # True for a cached copy of a user that lives on a remote server.
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    # E2EE fields
    identity_pub_ed25519: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), nullable=True
    )
    identity_pub_x25519: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), nullable=True
    )

    # Key backup fields
    encrypted_backup: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    backup_version: Mapped[int] = mapped_column(
        default=1, nullable=False, server_default="1"
    )

    @property
    def handle(self) -> str:
        """Full federated identity: ``username@server``."""
        return f"{self.username}@{self.server_name}"