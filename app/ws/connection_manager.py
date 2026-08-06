from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self._users: dict[int, set[WebSocket]] = defaultdict(set)
        self._user_rooms: dict[int, set[int]] = defaultdict(set)
        self._user_room_sockets: dict[tuple[int, int], set[WebSocket]] = defaultdict(
            set
        )

    async def connect(
        self, room_id: int, ws: WebSocket, user_id: int | None = None
    ) -> None:
        """Register a WebSocket for a room (for message broadcast)."""
        self._rooms[room_id].add(ws)
        if user_id is not None:
            self._user_rooms[user_id].add(room_id)
            self._user_room_sockets[(user_id, room_id)].add(ws)

    async def disconnect(self, room_id: int, ws: WebSocket) -> None:
        self._rooms[room_id].discard(ws)

    async def connect_user(self, user_id: int, ws: WebSocket) -> None:
        """Register a WebSocket for a user (for system notifications)."""
        self._users[user_id].add(ws)

    async def disconnect_user(self, user_id: int, ws: WebSocket) -> None:
        self._users[user_id].discard(ws)
        for room_id in list(self._user_rooms.get(user_id, ())):
            self._rooms[room_id].discard(ws)
            sockets = self._user_room_sockets.get((user_id, room_id))
            if sockets is not None:
                sockets.discard(ws)
                if not sockets:
                    del self._user_room_sockets[(user_id, room_id)]

    async def revoke_access(self, user_id: int, room_id: int) -> None:
        """Remove all of a user's sockets from a room (e.g. member left or removed)."""
        sockets = self._user_room_sockets.pop((user_id, room_id), set())
        for ws in sockets:
            self._rooms[room_id].discard(ws)
        self._user_rooms[user_id].discard(room_id)

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
