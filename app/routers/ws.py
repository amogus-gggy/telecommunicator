from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionLocal
from app.models.room import Room
from app.models.room_member import RoomMember
from app.models.user import User
from app.schemas.messages import WsInbound
from app.services.auth_service import decode_token
from app.services.message_service import send_message
from app.ws.connection_manager import manager

router = APIRouter(tags=["websocket"])


async def _get_user_from_token(token: str, db: AsyncSession) -> User | None:
    try:
        payload = decode_token(token)
    except Exception:
        return None
    user_id_str = payload.get("sub")
    if not user_id_str:
        return None
    result = await db.execute(select(User).where(User.id == int(user_id_str)))
    return result.scalar_one_or_none()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str | None = None, room_id: int | None = None) -> None:
    async with AsyncSessionLocal() as db:
        if not token:
            await ws.accept()
            await ws.send_json({"type": "error", "payload": "Not authenticated"})
            await ws.close(code=1008)
            return

        user = await _get_user_from_token(token, db)
        if user is None:
            await ws.accept()
            await ws.send_json({"type": "error", "payload": "Not authenticated"})
            await ws.close(code=1008)
            return

        await ws.accept()

        joined_rooms: set[int] = set()

        # Register this connection for user-level notifications (invites, etc.)
        await manager.connect_user(user.id, ws)

        # If room_id provided as query param, subscribe immediately
        if room_id is not None:
            membership = await db.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id, RoomMember.user_id == user.id
                )
            )
            if membership.scalar_one_or_none() is not None:
                await manager.connect(room_id, ws)
                joined_rooms.add(room_id)

        try:
            while True:
                raw = await ws.receive_text()

                try:
                    frame = WsInbound.model_validate_json(raw)
                    print(f"[WS] Parsed frame: type={frame.type}, room_id={frame.room_id}, files={frame.files}")
                except (ValidationError, ValueError) as e:
                    print(f"[WS] Validation error: {e}")
                    await ws.send_json({"type": "error", "payload": "Invalid message format"})
                    continue

                froom_id = frame.room_id
                body = frame.body

                if not body or len(body) > 2000:
                    await ws.send_json({"type": "error", "payload": "Message body must be 1\u20132000 characters"})
                    continue

                # Single membership + room fetch — reused by send_message via `room=` kwarg
                membership = await db.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == froom_id, RoomMember.user_id == user.id
                    )
                )
                if membership.scalar_one_or_none() is None:
                    await ws.send_json({"type": "error", "payload": "Not a member of this room"})
                    continue

                room = await db.get(Room, froom_id)
                if room is None:
                    await ws.send_json({"type": "error", "payload": "Room not found"})
                    continue
                if room.read_only and room.owner_id != user.id:
                    await ws.send_json({"type": "error", "payload": "Room is read-only; only the owner can send messages"})
                    continue

                # Ensure subscribed to this room
                if froom_id not in joined_rooms:
                    await manager.connect(froom_id, ws)
                    joined_rooms.add(froom_id)

                try:
                    # Pass room to avoid a second fetch inside send_message
                    files_list = frame.files if frame.files is not None else []
                    await send_message(room_id=froom_id, body=body, author=user, db=db, room=room, files=files_list)
                except Exception as exc:
                    detail = getattr(exc, "detail", str(exc))
                    await ws.send_json({"type": "error", "payload": detail})

        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect_user(user.id, ws)
            for rid in joined_rooms:
                await manager.disconnect(rid, ws)
