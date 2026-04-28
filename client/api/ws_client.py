"""
Unified WebSocket client.

A single persistent connection handles both room messages and user-level
notifications.  The server already supports this: room_id is optional on
connect, and the server subscribes the socket to a room the first time it
receives a message for that room (or via the initial query param).

Usage
-----
    client = UnifiedWsClient(
        token="...",
        on_room_message=handle_msg,       # called for type=="message" / "encrypted_message"
        on_notification=handle_notif,     # called for type=="invite" / "member_joined" / etc.
        on_reconnecting=handle_reconnect,
    )
    # Optionally subscribe to a room on connect:
    client.set_room(room_id)
    await client.connect()          # runs forever (call in a task)

    # Switch rooms without reconnecting:
    client.set_room(new_room_id)

    # Send a chat message:
    await client.send_message(room_id, body, files)

    # Shut down:
    client.close()

Backwards-compatible shims
--------------------------
WsClient and NotificationClient are kept as thin wrappers so existing
call-sites in room_view / chat_list_view / room_list_view continue to work
without changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import websockets
import websockets.exceptions

from config import WS_URL

logger = logging.getLogger(__name__)


class UnifiedWsClient:
    """Single WebSocket connection for both room messages and notifications."""

    _INITIAL_DELAY = 1.0
    _MAX_DELAY = 30.0

    def __init__(
        self,
        token: str,
        on_room_message: Callable[[dict], None] | None = None,
        on_notification: Callable[[dict], None] | None = None,
        on_reconnecting: Callable[[float], None] | None = None,
        ws_url: str | None = None,
    ) -> None:
        self._token = token
        self._on_room_message = on_room_message
        self._on_notification = on_notification
        self._on_reconnecting = on_reconnecting
        self._ws_url = ws_url or WS_URL
        self._closed = False
        self._ws = None
        # Current room the client is subscribed to (sent as query param on connect)
        self._room_id: int | None = None

    def set_room(self, room_id: int | None) -> None:
        """Set the room to subscribe to on the next (re)connect."""
        self._room_id = room_id

    async def connect(self) -> None:
        """Connect and loop forever with exponential back-off on failure."""
        delay = self._INITIAL_DELAY
        while not self._closed:
            url = f"{self._ws_url}?token={self._token}"
            if self._room_id is not None:
                url += f"&room_id={self._room_id}"
            try:
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    delay = self._INITIAL_DELAY
                    logger.debug("[WS] Connected (room_id=%s)", self._room_id)
                    async for raw in ws:
                        if self._closed:
                            break
                        self._dispatch(raw)
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError,
            ) as exc:
                logger.debug("[WS] Connection lost: %s", exc)
            finally:
                self._ws = None

            if self._closed:
                break

            if self._on_reconnecting is not None:
                self._on_reconnecting(delay)

            logger.debug("[WS] Reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._MAX_DELAY)

    def _dispatch(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            return

        msg_type = payload.get("type", "")

        # Room-level frames
        if msg_type in ("message", "encrypted_message"):
            if self._on_room_message is not None:
                try:
                    self._on_room_message(payload)
                except Exception as exc:
                    logger.error("[WS] on_room_message raised: %s", exc, exc_info=True)
        else:
            # Everything else is a notification (invite, member_joined, error, …)
            if self._on_notification is not None:
                try:
                    self._on_notification(payload)
                except Exception as exc:
                    logger.error("[WS] on_notification raised: %s", exc, exc_info=True)

    async def send_message(
        self,
        room_id: int,
        body: str,
        files: list[dict] | None = None,
    ) -> None:
        if self._ws is None:
            logger.warning("[WS] send_message called but not connected")
            return
        frame: dict = {"type": "message", "room_id": room_id, "body": body}
        if files:
            frame["files"] = files
        await self._ws.send(json.dumps(frame))

    def close(self) -> None:
        """Signal the client to stop and close the underlying socket."""
        self._closed = True
        if self._ws is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._ws.close())
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# Backwards-compatible shims
# ---------------------------------------------------------------------------

class WsClient(UnifiedWsClient):
    """Shim: behaves like the old WsClient (room-only messages)."""

    def __init__(
        self,
        token: str,
        room_id: int,
        on_message: Callable[[dict], None],
        on_reconnecting: Callable[[float], None] | None = None,
        ws_url: str | None = None,
    ) -> None:
        super().__init__(
            token=token,
            on_room_message=on_message,
            on_reconnecting=on_reconnecting,
            ws_url=ws_url,
        )
        self.set_room(room_id)


class NotificationClient(UnifiedWsClient):
    """Shim: behaves like the old NotificationClient (notifications only)."""

    def __init__(
        self,
        token: str,
        on_notification: Callable[[dict], None],
        ws_url: str | None = None,
    ) -> None:
        super().__init__(
            token=token,
            on_notification=on_notification,
            ws_url=ws_url,
        )
