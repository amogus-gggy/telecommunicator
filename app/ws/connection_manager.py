from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self._users: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, room_id: int, ws: WebSocket) -> None:
        """Register a WebSocket for a room (for message broadcast)."""
        self._rooms[room_id].add(ws)

    async def disconnect(self, room_id: int, ws: WebSocket) -> None:
        self._rooms[room_id].discard(ws)

    async def connect_user(self, user_id: int, ws: WebSocket) -> None:
        """Register a WebSocket for a user (for system notifications)."""
        self._users[user_id].add(ws)

    async def disconnect_user(self, user_id: int, ws: WebSocket) -> None:
        self._users[user_id].discard(ws)

    async def broadcast(self, room_id: int, payload: dict) -> None:
        sockets = list(self._rooms.get(room_id, set()))
        print(f"[BROADCAST] Room {room_id} has {len(sockets)} connected sockets")
        for i, ws in enumerate(sockets):
            try:
                print(f"[BROADCAST] Sending to socket {i + 1}/{len(sockets)}")
                await ws.send_json(payload)
                print(f"[BROADCAST] Successfully sent to socket {i + 1}")
            except Exception as e:
                print(f"[BROADCAST] Failed to send to socket {i + 1}: {e}")
                self._rooms[room_id].discard(ws)

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        """Send a notification frame to all connections of a specific user."""
        sockets = list(self._users.get(user_id, set()))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                self._users[user_id].discard(ws)


manager = ConnectionManager()
