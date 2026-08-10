"""Inbound server-to-server federation endpoints.

These endpoints are called by *other* homeservers (never by clients) and are
protected by the federated Ed25519 signature scheme.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.models.room import Room
from app.models.room_member import RoomMember
from app.models.user import User
from app.schemas import federation as fed
from app.services import message_service
from app.services.federation_service import (
    SERVER_NAME,
    cache_remote_user,
    find_local_user,
    get_local_server,
    user_payload,
    verify_request,
)

router = APIRouter(prefix="/federation", tags=["federation"])


async def _read_body(request: Request) -> bytes:
    return await request.body()


@router.post("/hello", response_model=fed.FederationHelloResponse)
async def federation_hello(
    body: fed.FederationHelloRequest,
    db: AsyncSession = Depends(get_db),
):
    """Discovery/bootstrap: returns this server's canonical name, base URL and
    Ed25519 key. ``server_name`` is OUR canonical identity, which the caller
    must use to key us — not the host it guessed or typed."""
    local = await get_local_server(db)
    return fed.FederationHelloResponse(
        server_name=local.server_name,
        base_url=local.base_url,
        public_key=(
            base64.b64encode(local.public_key).decode() if local.public_key else None
        ),
    )


@router.post("/user/lookup", response_model=fed.FederationUserLookupResponse)
async def federation_user_lookup(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> fed.FederationUserLookupResponse:
    raw = await _read_body(request)
    await verify_request(db, request, raw)
    try:
        body = fed.FederationUserLookupRequest.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    local = await get_local_server(db)
    result = await db.execute(
        select(User).where(
            User.username == body.username, User.server_name == local.server_name
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        return fed.FederationUserLookupResponse(found=False, username=body.username)
    return fed.FederationUserLookupResponse(found=True, **user_payload(user))


async def _member_to_user(db: AsyncSession, member: fed.FederationMember) -> User:
    """Resolve or cache a member row locally (local users pass through unchanged)."""

    def _b64(value: str | None) -> bytes | None:
        try:
            return base64.b64decode(value) if value else None
        except Exception:
            return None

    if member.server_name == SERVER_NAME:
        user = await find_local_user(db, member.username, SERVER_NAME)
        if user is None:
            raise HTTPException(status_code=404, detail="Local member not found")
        return user

    return await cache_remote_user(
        db,
        member.username,
        member.server_name,
        display_name=member.display_name,
        identity_pub_ed25519=_b64(member.identity_pub_ed25519),
        identity_pub_x25519=_b64(member.identity_pub_x25519),
    )


async def _add_room_members(
    db: AsyncSession, room: Room, members: list[fed.FederationMember]
) -> None:
    for member in members:
        user = await _member_to_user(db, member)
        existing = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room.id, RoomMember.user_id == user.id
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(RoomMember(room_id=room.id, user_id=user.id))
    # Keep the owner in the roster even if the incoming roster omits them —
    # an owner who is not a member is a broken state.
    if room.owner_id:
        owner_exists = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room.id, RoomMember.user_id == room.owner_id
            )
        )
        if owner_exists.scalar_one_or_none() is None:
            db.add(RoomMember(room_id=room.id, user_id=room.owner_id))
    await db.commit()


async def _resolve_room_owner(
    db: AsyncSession, body: fed.FederationRoomImportRequest
) -> User:
    """Return a concrete user to own a mirror room.

    The real owner is the host's owner (`body.owner` when provided). Prefer it;
    otherwise fall back to the first member so `rooms.owner_id` never references
    a non-existent row (owner_id=0).
    """
    owner_member = body.owner
    if owner_member is None and body.members:
        owner_member = body.members[0]
    if owner_member is None:
        raise HTTPException(
            status_code=400,
            detail="Room import requires at least one member (owner)",
        )
    return await _member_to_user(db, owner_member)


@router.post("/rooms/import", response_model=fed.FederationRoomImportResponse)
async def federation_room_import(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> fed.FederationRoomImportResponse:
    """Create a local mirror room for a room hosted on the sender's server."""
    raw = await _read_body(request)
    sender = await verify_request(db, request, raw)
    try:
        body = fed.FederationRoomImportRequest.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    host_server = sender.server_name

    result = await db.execute(
        select(Room).where(
            Room.server_name == host_server, Room.remote_room_id == body.remote_room_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        # Refresh roster (host is source of truth) but keep the current owner.
        await db.execute(
            RoomMember.__table__.delete().where(RoomMember.room_id == existing.id)
        )
        await _add_room_members(db, existing, body.members)
        return fed.FederationRoomImportResponse(
            local_room_id=existing.id, remote_room_id=body.remote_room_id
        )

    owner_row = await _resolve_room_owner(db, body)
    room = Room(
        name=body.name,
        room_type=body.room_type,
        owner_id=owner_row.id,
        is_private=body.is_private,
        server_name=host_server,
        remote_room_id=body.remote_room_id,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)

    await _add_room_members(db, room, body.members)
    return fed.FederationRoomImportResponse(
        local_room_id=room.id, remote_room_id=body.remote_room_id
    )


@router.post("/rooms/{room_id}/message")
async def federation_room_message(
    room_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive a message relayed into the local room `room_id`.

    Authorization:
    * The body's ``sender.server_name`` must equal the signing server — a relay
      is only ever produced *by* the author's own homeserver, so any mismatch is
      a forged author (in particular, it prevents impersonating a local user).
    * The sender must be a member of the room (mirrors carry the roster, so a
      legitimately relayed author was imported as a member).
    * Mirror rooms may only receive relays from their hosting server.
    """
    raw = await _read_body(request)
    sender = await verify_request(db, request, raw)
    try:
        body = fed.FederationRoomMessage.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    # The signing server must be the author's home server — a relay is only ever
    # produced by the server that hosts the author.
    if body.sender.server_name != sender.server_name:
        raise HTTPException(
            status_code=403, detail="Relay sender does not match author's server"
        )

    # Only the hosting server may push messages into a mirror room.
    if room.server_name != SERVER_NAME and sender.server_name != room.server_name:
        raise HTTPException(
            status_code=403,
            detail="Only the hosting server may relay into a mirror room",
        )

    author = await _member_to_user(db, body.sender)
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room.id, RoomMember.user_id == author.id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403, detail="Author is not a member of this room"
        )

    await message_service.store_and_relay(
        db, room=room, author=author, payload=body.payload
    )
    return {"status": "ok", "room_id": room.id}