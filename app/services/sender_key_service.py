"""Sender-key distribution storage and cross-server assembly.

Each sender's client uploads one opaque distribution blob per room member to
its own homeserver. Recipients read the blobs addressed to them locally and —
for senders hosted elsewhere — through a signed federation fetch, so a group
room works across federated servers.
"""

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Room
from app.models.room_member import RoomMember
from app.models.sender_key import SenderKey
from app.models.user import User
from app.schemas.federation import FederationMember
from app.schemas.sender_keys import SenderKeyBlob, SenderKeyEntry, SenderKeysResponse
from app.services.federation_service import (
    SERVER_NAME,
    ensure_server,
    fetch_sender_keys_from_server,
    resolve_user,
    user_member_payload,
)

logger = logging.getLogger(__name__)


def _member_handle(user: User) -> str:
    """Full ``username@server`` handle; bare username for local users."""
    if user.server_name and user.server_name != SERVER_NAME:
        return f"{user.username}@{user.server_name}"
    return user.username


def _is_remote(user: User) -> bool:
    return bool(user.server_name) and user.server_name != SERVER_NAME


async def _get_member(db: AsyncSession, room_id: int, user_id: int) -> RoomMember | None:
    result = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def _get_room(db: AsyncSession, room_id: int, user: User) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if await _get_member(db, room_id, user.id) is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")
    return room


def _host_ref(room: Room) -> tuple[str, int]:
    """(host server name, room id on the host) for federation addressing."""
    if room.server_name != SERVER_NAME and room.remote_room_id is not None:
        return room.server_name, room.remote_room_id
    return SERVER_NAME, room.id


async def upsert_sender_keys(
    db: AsyncSession,
    room_id: int,
    sender: User,
    entries: list[SenderKeyEntry],
) -> int:
    """Store/replace the sender's distribution blobs for a room.

    Only members can publish, and only to members; blobs for a lower generation
    than the stored one are ignored so a stale retry cannot roll a rotation back.
    """
    if await _get_member(db, room_id, sender.id) is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    stored = 0
    for entry in entries:
        try:
            recipient = await resolve_user(db, entry.recipient_username)
        except HTTPException:
            continue
        if recipient.id == sender.id:
            continue
        if await _get_member(db, room_id, recipient.id) is None:
            continue

        result = await db.execute(
            select(SenderKey).where(
                SenderKey.room_id == room_id,
                SenderKey.sender_id == sender.id,
                SenderKey.recipient_id == recipient.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = SenderKey(
                room_id=room_id, sender_id=sender.id, recipient_id=recipient.id
            )
            db.add(row)
        elif entry.generation < row.generation:
            continue
        row.generation = entry.generation
        row.blob = entry.blob
        stored += 1

    await db.commit()
    return stored


async def _fetch_remote_sender_key(
    db: AsyncSession, room: Room, recipient: User, sender: User
) -> list[SenderKeyBlob]:
    """Fetch ``sender``'s distribution blob for ``recipient`` from the sender's
    homeserver. Best-effort: an unreachable server yields no keys."""
    host_server_name, host_room_id = _host_ref(room)
    try:
        server = await ensure_server(db, sender.server_name)
        raw_keys = await fetch_sender_keys_from_server(
            db,
            server,
            host_server_name=host_server_name,
            host_room_id=host_room_id,
            recipient=user_member_payload(recipient),
            sender=user_member_payload(sender),
        )
    except HTTPException as exc:
        logger.warning(
            "[SenderKeys] Fetch from %s failed: %s", sender.server_name, exc.detail
        )
        return []
    keys: list[SenderKeyBlob] = []
    for item in raw_keys:
        try:
            keys.append(
                SenderKeyBlob(
                    sender_username=item["sender_username"],
                    generation=item["generation"],
                    blob=item["blob"],
                )
            )
        except (KeyError, TypeError):
            continue
    return keys


async def get_sender_keys(
    db: AsyncSession,
    room_id: int,
    user: User,
    sender_handle: str | None = None,
) -> SenderKeysResponse:
    """Assemble every sender-key blob addressed to ``user`` for a room.

    Local rows cover senders hosted here; for each remote sender the blob is
    fetched from their homeserver (addressed by the hosting server's room id).
    """
    room = await _get_room(db, room_id, user)

    keys: dict[str, SenderKeyBlob] = {}

    stmt = (
        select(SenderKey, User)
        .join(User, SenderKey.sender_id == User.id)
        .where(SenderKey.room_id == room_id, SenderKey.recipient_id == user.id)
    )
    if sender_handle:
        try:
            sender_user = await resolve_user(db, sender_handle)
        except HTTPException:
            sender_user = None
        if sender_user is None:
            return SenderKeysResponse(room_id=room_id, keys=[])
        stmt = stmt.where(SenderKey.sender_id == sender_user.id)
    result = await db.execute(stmt)
    for row, sender_user in result.all():
        keys[_member_handle(sender_user)] = SenderKeyBlob(
            sender_username=_member_handle(sender_user),
            generation=row.generation,
            blob=row.blob,
        )

    if sender_handle:
        if _is_remote(sender_user) and _member_handle(sender_user) not in keys:
            for key in await _fetch_remote_sender_key(db, room, user, sender_user):
                keys[key.sender_username] = key
        return SenderKeysResponse(room_id=room_id, keys=list(keys.values()))

    # Full-room fetch: pull every remote member's blob from their homeserver.
    members_result = await db.execute(
        select(User)
        .join(RoomMember, RoomMember.user_id == User.id)
        .where(RoomMember.room_id == room_id)
    )
    for member in members_result.scalars():
        if not _is_remote(member) or member.id == user.id:
            continue
        handle = _member_handle(member)
        if handle in keys:
            continue
        for key in await _fetch_remote_sender_key(db, room, user, member):
            keys[key.sender_username] = key

    return SenderKeysResponse(room_id=room_id, keys=list(keys.values()))


async def get_sender_keys_for_federation(
    db: AsyncSession,
    host_server_name: str,
    host_room_id: int,
    recipient_member: dict,
    sender_member: dict | None,
) -> list[dict]:
    """Serve a signed federation fetch: blobs stored here, addressed to
    ``recipient_member``, authored by local senders of this server.

    The room is located via the hosting server's coordinates (this server may
    host the room or hold a mirror of it).
    """
    from app.routers.federation import _member_to_user

    recipient_model = FederationMember.model_validate(recipient_member)
    sender_model = (
        FederationMember.model_validate(sender_member)
        if sender_member is not None
        else None
    )

    if host_server_name == SERVER_NAME:
        room = await db.get(Room, host_room_id)
        if room is None or room.server_name != SERVER_NAME:
            raise HTTPException(status_code=404, detail="Room not found")
    else:
        result = await db.execute(
            select(Room).where(
                Room.server_name == host_server_name,
                Room.remote_room_id == host_room_id,
            )
        )
        room = result.scalar_one_or_none()
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")

    recipient = await _member_to_user(db, recipient_model)
    if await _get_member(db, room.id, recipient.id) is None:
        raise HTTPException(status_code=403, detail="Recipient is not a member")

    stmt = select(SenderKey, User).join(
        User, SenderKey.sender_id == User.id
    ).where(
        SenderKey.room_id == room.id,
        SenderKey.recipient_id == recipient.id,
        # A server only ever serves blobs its own users uploaded.
        User.server_name == SERVER_NAME,
    )
    if sender_model is not None:
        sender = await _member_to_user(db, sender_model)
        stmt = stmt.where(SenderKey.sender_id == sender.id)

    result = await db.execute(stmt)
    return [
        {
            "sender_username": _member_handle(sender_user),
            "generation": row.generation,
            "blob": row.blob,
        }
        for row, sender_user in result.all()
    ]
