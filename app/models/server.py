from datetime import datetime

from sqlalchemy import Boolean, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Server(Base):
    """A homeserver in the federation.

    The row whose ``server_name`` equals the local settings value is "this"
    instance and also carries the locally generated Ed25519 keypair used to
    sign outgoing federation requests. Every other row describes a *remote*
    homeserver we have talked to and lets us verify its signatures.
    """

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Ed25519 identity key used to sign/verify federation requests.
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    # Only populated on the local row (never exposed over the API).
    private_key: Mapped[bytes | None] = mapped_column(LargeBinary(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=func.now())