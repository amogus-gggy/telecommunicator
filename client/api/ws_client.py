from __future__ import annotations

import asyncio
import json
from typing import Callable

import websockets
import websockets.exceptions

from client.config import WS_URL


class WsClient:
    """WebSocket client with exponential back-off reconnect logic."""

    _INITIAL_DELAY = 1.0
    _MAX_DELAY = 30.0

    def __init__(
        self,
        token: str,
        room_id: int,
        on_message: Callable[[dict], None],
        on_reconnecting: Callable[[float], None] | None = None,
        ws_url: str | None = None,
    ) -> None:
        self._token = token
        self._room_id = room_id
        self._on_message = on_message
        self._on_reconnecting = on_reconnecting
        self._closed = False
        self._ws = None
        self._ws_url = ws_url or WS_URL

    async def connect(self) -> None:
        """Start the connection loop with exponential back-off reconnect."""
        delay = self._INITIAL_DELAY
        while not self._closed:
            url = f"{self._ws_url}?token={self._token}&room_id={self._room_id}"
            try:
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    delay = self._INITIAL_DELAY
                    async for raw in ws:
                        if self._closed:
                            break
                        try:
                            payload = json.loads(raw)
                            self._on_message(payload)
                        except Exception:
                            pass
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError,
            ):
                pass
            finally:
                self._ws = None

            if self._closed:
                break

            if self._on_reconnecting is not None:
                self._on_reconnecting(delay)

            await asyncio.sleep(delay)
            delay = min(delay * 2, self._MAX_DELAY)

    async def send_message(self, room_id: int, body: str) -> None:
        """Send a WsInbound message frame."""
        if self._ws is None:
            return
        frame = json.dumps({"type": "message", "room_id": room_id, "body": body})
        await self._ws.send(frame)

    def close(self) -> None:
        """Signal the client to stop reconnecting."""
        self._closed = True
        if self._ws is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._ws.close())
            except RuntimeError:
                pass


class NotificationClient:
    """Global WebSocket connection for user-level notifications (invites, etc.)."""

    _INITIAL_DELAY = 1.0
    _MAX_DELAY = 30.0

    def __init__(
        self,
        token: str,
        on_notification: Callable[[dict], None],
        ws_url: str | None = None,
    ) -> None:
        self._token = token
        self._on_notification = on_notification
        self._closed = False
        self._ws_url = ws_url or WS_URL

    async def connect(self) -> None:
        delay = self._INITIAL_DELAY
        while not self._closed:
            # Connect without room_id — only receives user-level frames
            url = f"{self._ws_url}?token={self._token}"
            try:
                async with websockets.connect(url) as ws:
                    delay = self._INITIAL_DELAY
                    async for raw in ws:
                        if self._closed:
                            break
                        try:
                            payload = json.loads(raw)
                            self._on_notification(payload)
                        except Exception:
                            pass
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError,
            ):
                pass

            if self._closed:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._MAX_DELAY)

    def close(self) -> None:
        self._closed = True
