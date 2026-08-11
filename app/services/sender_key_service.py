"""
Group E2EE (sender keys) — server side.

The server is a blind router here. It never sees a group plaintext and never
sees a chain key: it only stores/forwards

* **sender-key bundles** — one per (room, sender, recipient, chain), whose
  payload is the sender's chain key already encrypted with the *pairwise*
  Double Ratchet session between the two users, and
* **v3 ciphertexts** — the group messages themselves, encrypted once with the
  sender's chain and fanned out to the room.

Its only cryptographic responsibility is the ``key_epoch`` counter: it is
bumped on every membership change so that clients rotate their chain before the
next message and a removed member cannot read anything sent after they left.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.file import File
from app.models.message import Message
from app.models.room import Room, RoomType
from app.models.room_member import RoomMember
from app.models.sender_key import SenderKeyDistribution
from app.models.user import User
from app.schemas.messages import SendMessageResponse
from app.schemas.sender_keys import (
    SenderKeyBundle,
    SenderKeyBundleResponse,
    SenderKeyDistributionResponse,
    SenderKeyStateResponse,
)
from app.services.federation_service import SERVER_NAME, resolve_user
from app.services.message_service import (
    _author_handle,
    _new_event_id,
    _relay_message,
    _relay_payload,
)
from app.ws.connection_manager import manager

logger = logging.getLogger(__name__)

#: Rooms whose messages use the sender-key scheme (personal chats keep the
#: pairwise Double Ratchet, which is strictly stronger for two parties).
GROUP_ROOM_TYPES = (RoomType.GROUP, RoomType.PUBLIC)

#: Guard against a client dumping unbounded key material on the server.
MAX_BUNDLE_BYTES = 64 * 1024


def _member_handle(user: User) -> str:
    if user.server_name and user.server_name != SERVER_NAME:
        return f"{user.username}@{user.server_name}"
    return user.username


def _b64decode(value: str, field: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field} is not valid base64")
    if not raw:
        raise HTTPException(status_code=400, detail=f"{field} must not be empty")
    if len(raw) > MAX_BUNDLE_BYTES:
        raise HTTPException(status_code=413, detail=f"{field} is too large")
    return raw


async def _require_membership(db: AsyncSession, room_id: int, user_id: int) -> None:
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user_id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")


async def _require_room(db: AsyncSession, room_id: int) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


async def _room_member_users(db: AsyncSession, room_id: int) -> list[User]:
    result = await db.execute(
        select(User).join(RoomMember, RoomMember.user_id == User.id).where(
            RoomMember.room_id == room_id
        )
    )
    return list(result.scalars())


def room_key_epoch(room: Room) -> int:
    return int(getattr(room, "key_epoch", 1) or 1)


# ---------------------------------------------------------------------------
# Membership changes → rotation trigger
# ---------------------------------------------------------------------------


async def bump_key_epoch(db: AsyncSession, room_id: int) -> int:
    """Invalidate every sender chain of a room after a membership change.

    Called from the room service on join / invite / leave / removal. Every
    remaining member learns from the new epoch that it must distribute a fresh
    chain before its next message.

    Undelivered bundles addressed to users who are *no longer members* are
    deleted, so a removed (or re-joining) member can never pick up a chain that
    is still in use. Bundles addressed to current members are kept even though
    their epoch is now stale: they protect messages that were legitimately sent
    before the rotation, and a member who was offline across the rotation still
    has to be able to read them.
    """
    room = await db.get(Room, room_id)
    if room is None:
        return 1
    new_epoch = room_key_epoch(room) + 1
    await db.execute(
        update(Room).where(Room.id == room_id).values(key_epoch=new_epoch)
    )
    members = await _room_member_users(db, room_id)
    member_ids = {m.id for m in members}
    stale = await db.execute(
        select(SenderKeyDistribution).where(
            SenderKeyDistribution.room_id == room_id,
            SenderKeyDistribution.key_epoch < new_epoch,
        )
    )
    for row in stale.scalars():
        if row.recipient_id not in member_ids or row.sender_id not in member_ids:
            await db.delete(row)
    await db.commit()

    # Tell everyone still in the room to rotate; the payload carries no secrets.
    for member in members:
        try:
            await manager.send_to_user(
                member.id,
                {
                    "type": "sender_key_rotation",
                    "payload": {"room_id": room_id, "key_epoch": new_epoch},
                },
            )
        except Exception:  # noqa: BLE001 - notification is best-effort
            logger.debug("[SenderKey] rotation notice failed for user %s", member.id)
    return new_epoch


# ---------------------------------------------------------------------------
# Key state / distribution
# ---------------------------------------------------------------------------


async def get_key_state(
    db: AsyncSession, room_id: int, user: User
) -> SenderKeyStateResponse:
    """Current epoch + member handles, so a client can target its bundles."""
    room = await _require_room(db, room_id)
    await _require_membership(db, room_id, user.id)
    members = await _room_member_users(db, room_id)
    return SenderKeyStateResponse(
        room_id=room_id,
        key_epoch=room_key_epoch(room),
        members=sorted(_member_handle(m) for m in members),
    )


async def store_distributions(
    db: AsyncSession,
    room_id: int,
    sender: User,
    chain_id: str,
    key_epoch: int,
    bundles: list[SenderKeyBundle],
) -> SenderKeyDistributionResponse:
    """Persist (and push) one pairwise-encrypted chain bundle per recipient."""
    room = await _require_room(db, room_id)
    await _require_membership(db, room_id, sender.id)

    current_epoch = room_key_epoch(room)
    if key_epoch < current_epoch:
        # The membership changed while the client was building its bundles;
        # ask it to rotate again rather than distributing a doomed chain.
        raise HTTPException(
            status_code=409,
            detail=f"Stale key_epoch: room is at epoch {current_epoch}",
        )

    members = {m.id: m for m in await _room_member_users(db, room_id)}
    stored = 0
    skipped: list[str] = []

    for bundle in bundles:
        blob = _b64decode(bundle.encrypted_blob, "encrypted_blob")
        signature = _b64decode(bundle.signature, "signature")

        try:
            recipient = await resolve_user(db, bundle.recipient_username)
        except HTTPException:
            skipped.append(bundle.recipient_username)
            continue
        if recipient.id not in members or recipient.id == sender.id:
            # Never store key material for a non-member: that is exactly the
            # leak the epoch mechanism exists to prevent.
            skipped.append(bundle.recipient_username)
            continue

        existing = await db.execute(
            select(SenderKeyDistribution).where(
                SenderKeyDistribution.room_id == room_id,
                SenderKeyDistribution.sender_id == sender.id,
                SenderKeyDistribution.recipient_id == recipient.id,
                SenderKeyDistribution.chain_id == chain_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = SenderKeyDistribution(
                room_id=room_id,
                sender_id=sender.id,
                recipient_id=recipient.id,
                chain_id=chain_id,
                key_epoch=key_epoch,
            )
            db.add(row)
        row.encrypted_blob = blob
        row.signature = signature
        row.key_epoch = key_epoch
        row.delivered_at = None
        stored += 1

    # A new chain supersedes the sender's previous ones for this room.
    superseded = await db.execute(
        select(SenderKeyDistribution).where(
            SenderKeyDistribution.room_id == room_id,
            SenderKeyDistribution.sender_id == sender.id,
            SenderKeyDistribution.chain_id != chain_id,
        )
    )
    for row in superseded.scalars():
        await db.delete(row)

    await db.commit()

    # Push so an online member can decrypt the very next message immediately.
    sender_handle = _author_handle(sender)
    for bundle in bundles:
        try:
            recipient = await resolve_user(db, bundle.recipient_username)
        except HTTPException:
            continue
        if recipient.id not in members or recipient.id == sender.id:
            continue
        try:
            await manager.send_to_user(
                recipient.id,
                {
                    "type": "sender_key_bundle",
                    "payload": {
                        "room_id": room_id,
                        "sender_id": sender.id,
                        "sender_username": sender_handle,
                        "chain_id": chain_id,
                        "key_epoch": key_epoch,
                        "encrypted_blob": bundle.encrypted_blob,
                        "signature": bundle.signature,
                    },
                },
            )
        except Exception:  # noqa: BLE001 - polling covers offline members
            logger.debug("[SenderKey] bundle push failed for %s", recipient.id)

    return SenderKeyDistributionResponse(
        stored=stored, skipped=skipped, key_epoch=key_epoch
    )


async def fetch_bundles(
    db: AsyncSession,
    user: User,
    room_id: int | None = None,
    include_delivered: bool = False,
) -> list[SenderKeyBundleResponse]:
    """Return the chain bundles addressed to *user* (catch-up after offline)."""
    stmt = (
        select(SenderKeyDistribution, User)
        .join(User, SenderKeyDistribution.sender_id == User.id)
        .where(SenderKeyDistribution.recipient_id == user.id)
    )
    if room_id is not None:
        await _require_membership(db, room_id, user.id)
        stmt = stmt.where(SenderKeyDistribution.room_id == room_id)
    if not include_delivered:
        stmt = stmt.where(SenderKeyDistribution.delivered_at.is_(None))
    stmt = stmt.order_by(SenderKeyDistribution.created_at.asc())

    rows = (await db.execute(stmt)).all()
    now = datetime.now(timezone.utc)
    responses: list[SenderKeyBundleResponse] = []
    for row, sender in rows:
        row.delivered_at = row.delivered_at or now
        responses.append(
            SenderKeyBundleResponse(
                id=row.id,
                room_id=row.room_id,
                sender_id=row.sender_id,
                sender_username=_author_handle(sender),
                chain_id=row.chain_id,
                key_epoch=row.key_epoch,
                encrypted_blob=base64.b64encode(row.encrypted_blob).decode(),
                signature=base64.b64encode(row.signature).decode(),
                created_at=row.created_at,
            )
        )
    if rows:
        await db.commit()
    return responses


# ---------------------------------------------------------------------------
# Group message send
# ---------------------------------------------------------------------------


async def send_group_message(
    db: AsyncSession,
    room_id: int,
    sender: User,
    encrypted_blob: bytes,
    signature: bytes,
    chain_id: str,
    key_epoch: int,
    file_ids: list[int] | None = None,
) -> SendMessageResponse:
    """Persist and fan out one sender-key encrypted group message."""
    room = await _require_room(db, room_id)
    await _require_membership(db, room_id, sender.id)

    if room.read_only and room.owner_id != sender.id:
        raise HTTPException(
            status_code=403,
            detail="Room is read-only; only the owner can send messages",
        )

    current_epoch = room_key_epoch(room)
    if key_epoch < current_epoch:
        # Membership changed since the chain was built — reject so the client
        # rotates instead of encrypting to an audience that no longer matches.
        raise HTTPException(
            status_code=409,
            detail=f"Stale key_epoch: room is at epoch {current_epoch}",
        )

    msg = Message(
        room_id=room_id,
        author_id=sender.id,
        encrypted_blob=encrypted_blob,
        # v3 carries no sender copy: the author owns the chain and can derive
        # its own message keys, so there is nothing extra to store.
        sender_encrypted_blob=None,
        signature=signature,
        recipient_id=None,
        is_encrypted=True,
        event_id=_new_event_id(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    if file_ids:
        for fid in file_ids:
            file_orm = await db.get(File, fid)
            if file_orm is not None and file_orm.room_id == room_id:
                file_orm.message_id = msg.id
        await db.commit()

    loaded = (
        await db.execute(
            select(Message)
            .options(selectinload(Message.files))
            .where(Message.id == msg.id)
        )
    ).scalar_one()

    sender_handle = _author_handle(sender)
    files_payload = [
        {
            "id": f.id,
            "filename": f.filename,
            "room_id": f.room_id,
            "uploader_id": f.uploader_id,
            "uploader_username": sender_handle,
            "created_at": f.created_at.isoformat(),
            "is_encrypted": f.is_encrypted,
            "key_blob": f.key_blob,
            "key_sender_blob": f.key_sender_blob,
            "key_signature": f.key_signature,
        }
        for f in (loaded.files or [])
    ]

    blob_b64 = base64.b64encode(encrypted_blob).decode()
    signature_b64 = base64.b64encode(signature).decode()

    await manager.broadcast(
        room_id,
        {
            "type": "encrypted_message",
            "payload": {
                "message_id": msg.id,
                "sender_id": sender.id,
                "sender_username": sender_handle,
                "room_id": room_id,
                "encrypted_blob": blob_b64,
                "sender_encrypted_blob": None,
                "signature": signature_b64,
                "is_encrypted": True,
                "group": True,
                "chain_id": chain_id,
                "key_epoch": key_epoch,
                "created_at": msg.created_at.isoformat(),
                "files": files_payload,
            },
        },
    )

    # Federated fan-out: mirrors relay the opaque ciphertext unchanged.
    try:
        await _relay_message(
            db,
            room,
            sender,
            _relay_payload(
                author=sender,
                encrypted_blob=encrypted_blob,
                signature=signature,
                is_encrypted=True,
                event_id=msg.event_id,
            ),
        )
    except Exception:  # noqa: BLE001 - a remote must not break local delivery
        logger.warning("[SenderKey] federation relay failed for message %s", msg.id)

    return SendMessageResponse(
        message_id=msg.id, created_at=msg.created_at, delivered=True
    )
