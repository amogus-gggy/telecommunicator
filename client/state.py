from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from api.ws_client import WsClient, NotificationClient
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from crypto.key_cache import PublicKeyCache

# Module-level logger — created once, not on every attribute change
_logger = logging.getLogger(__name__)


@dataclass
class UserDTO:
    id: int
    username: str
    email: str
    display_name: str | None = None


@dataclass
class RoomDTO:
    id: int
    name: str
    room_type: str
    owner_username: str
    member_count: int
    is_private: bool
    allow_member_invite: bool
    read_only: bool


@dataclass
class AppState:
    token: str | None = None
    current_user: UserDTO | None = None
    active_room: RoomDTO | None = None
    message_alignment: str = "default"  # "default" | "left" | "right"
    secure_storage: Any = field(default=None, repr=False)
    # Active WebSocket connections — closed before creating new ones
    room_ws: "WsClient | None" = field(default=None, repr=False)
    notif_ws: "NotificationClient | None" = field(default=None, repr=False)
    # Callback invoked when message_alignment changes (set by room_view)
    on_alignment_change: "Callable[[str], None] | None" = field(default=None, repr=False)
    # E2EE cryptographic keys
    ed25519_private: "Ed25519PrivateKey | None" = field(default=None, repr=False)
    x25519_private: "X25519PrivateKey | None" = field(default=None, repr=False)
    old_x25519_private: "X25519PrivateKey | None" = field(default=None, repr=False)
    public_key_cache: "PublicKeyCache | None" = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.public_key_cache is None:
            try:
                from crypto.key_cache import PublicKeyCache
                self.public_key_cache = PublicKeyCache()
            except ImportError:
                pass  # Will be initialized later when crypto module is available

    def __setattr__(self, name: str, value: object) -> None:
        if name == "message_alignment":
            # Only fire callback when the value actually changes
            old = self.__dict__.get("message_alignment")
            object.__setattr__(self, name, value)
            if old != value:
                _logger.info(
                    "[AppState] message_alignment changed %r -> %r, callback=%s",
                    old,
                    value,
                    "set" if self.on_alignment_change is not None else "None",
                )
                if self.on_alignment_change is not None:
                    self.on_alignment_change(str(value))
        else:
            object.__setattr__(self, name, value)

    def close_room_ws(self) -> None:
        if self.room_ws is not None:
            self.room_ws.close()
            self.room_ws = None

    def close_notif_ws(self) -> None:
        if self.notif_ws is not None:
            self.notif_ws.close()
            self.notif_ws = None

    def clear_crypto_keys(self) -> None:
        """Clear cryptographic keys from memory."""
        self.ed25519_private = None
        self.x25519_private = None
        self.old_x25519_private = None
        if self.public_key_cache is not None:
            self.public_key_cache.clear()
