from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from client.api.ws_client import WsClient, NotificationClient


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

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
        if name == "message_alignment":
            import logging
            logging.getLogger(__name__).info(
                "[AppState] message_alignment set to %r, on_alignment_change=%s",
                value,
                "set" if self.on_alignment_change is not None else "None",
            )
            if self.on_alignment_change is not None:
                self.on_alignment_change(str(value))

    def close_room_ws(self) -> None:
        if self.room_ws is not None:
            self.room_ws.close()
            self.room_ws = None

    def close_notif_ws(self) -> None:
        if self.notif_ws is not None:
            self.notif_ws.close()
            self.notif_ws = None
