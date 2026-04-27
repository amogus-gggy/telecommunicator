import base64
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, desc # Import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload # Import selectinload

from app.models.file import File # Import File model
from app.models.message import Message
from app.models.room import Room
from app.models.room_member import RoomMember
from app.models.user import User
from app.schemas.messages import MessageResponse, SendMessageResponse  # MessageResponse now includes 'files'
from app.ws.connection_manager import manager

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


async def send_message(
    room_id: int,
    body: str,
    author: User,
    db: AsyncSession,
    *,
    room: Room | None = None,
    files: list[dict] | None = None, # Accept files argument
) -> MessageResponse:
    """Validate, persist, and broadcast a message. Raises HTTPException on failure.

    Pass ``room`` if you already have the Room object to avoid a redundant fetch.
    Processes and associates uploaded files with the message.
    """
    # Body validation (cheap, do first)
    if not body or len(body) > 2000:
        raise HTTPException(
            status_code=422, detail="Message body must be 1\u20132000 characters"
        )

    # Membership check
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == author.id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    # Room fetch (reuse if caller already has it)
    if room is None:
        room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.read_only and room.owner_id != author.id:
        raise HTTPException(
            status_code=403, detail="Room is read-only; only the owner can send messages"
        )

    # Persist Message
    msg = Message(room_id=room_id, author_id=author.id, body=body)
    db.add(msg)
    await db.commit()
    await db.refresh(msg) # Refresh to get msg.id
    print(f"[SEND_MESSAGE] Message persisted with ID: {msg.id}")

    # Associate files with the message
    if files and len(files) > 0:
        print(f"[SEND_MESSAGE] Processing {len(files)} files")
        for file_data in files:
            file_id = file_data.get("id")
            if file_id:
                # Fetch the File ORM object by its ID
                file_orm = await db.get(File, file_id)
                if file_orm:
                    # Ensure the file belongs to this room and was uploaded by this user
                    # If file upload is separate, we trust the client sent valid IDs.
                    # Additional checks could be added here (e.g., file_orm.room_id == room_id).
                    file_orm.message_id = msg.id
                    db.add(file_orm) # Add to session to track changes
                else:
                    print(f"Warning: File with ID {file_id} not found for message association.")
            else:
                print(f"Warning: File metadata missing 'id' field: {file_data}")
        await db.commit() # Commit file associations
        print("[SEND_MESSAGE] Files associated with message")
    else:
        print("[SEND_MESSAGE] No files to process")

    # Fetch message and its associated files for the response
    # Use selectinload to eager load the 'files' relationship
    stmt = (
        select(Message)
        .options(selectinload(Message.files)) # Eager load files
        .where(Message.id == msg.id)
    )
    result = await db.execute(stmt)
    message_with_files = result.scalar_one_or_none()

    if not message_with_files:
        raise HTTPException(status_code=500, detail="Failed to retrieve message after saving")

    # Construct MessageResponse, including files
    response_files = []
    if message_with_files.files:
        response_files = [
            {
                "id": f.id,
                "filename": f.filename,
                "uploader_id": f.uploader_id,
                "room_id": f.room_id,
                "created_at": f.created_at.isoformat(),
            }
            for f in message_with_files.files
        ]

    response = MessageResponse(
        id=message_with_files.id,
        room_id=message_with_files.room_id,
        author_username=author.username,
        author_display_name=author.display_name,
        body=message_with_files.body,
        created_at=message_with_files.created_at,
        files=response_files, # Populate files field
    )

    print(f"[SEND_MESSAGE] Broadcasting message {response.id} to room {room_id}")
    # Broadcast
    await manager.broadcast(
        room_id,
        {
            "type": "message",
            "payload": response.model_dump(mode='json'), # Use mode='json' for proper datetime serialization
        },
    )
    print(f"[SEND_MESSAGE] Broadcast completed for message {response.id}")

    return response


async def get_message_history(
    room_id: int,
    user: User,
    db: AsyncSession,
    before_id: int | None = None,
    limit: int = _DEFAULT_PAGE_SIZE,
) -> list[MessageResponse]:
    """Return paginated message history. Raises 403 if user is not a member."""
    limit = min(limit, _MAX_PAGE_SIZE)

    # Membership check
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    # Query for messages, authors, and associated files
    # Eager load the 'files' relationship for each message
    stmt = (
        select(Message, User)
        .join(User, Message.author_id == User.id) # Join with User to get author details
        .options(selectinload(Message.files)) # Eager load files relationship
        .where(Message.room_id == room_id)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)

    stmt = stmt.order_by(desc(Message.id)).limit(limit) # Order by ID descending for history

    result = await db.execute(stmt)
    rows_with_details = result.all() # List of (Message, User) tuples

    message_responses = []
    for msg_orm, author_orm in rows_with_details:
        message_files = []
        if msg_orm.files: # Check if files relationship is loaded and not empty
            message_files = [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "uploader_id": f.uploader_id,
                    "room_id": f.room_id,
                    "created_at": f.created_at.isoformat(),
                }
                for f in msg_orm.files
            ]

        message_responses.append(
            MessageResponse(
                id=msg_orm.id,
                room_id=msg_orm.room_id,
                author_username=author_orm.username,
                author_display_name=author_orm.display_name,
                body=msg_orm.body,
                is_encrypted=msg_orm.is_encrypted,
                encrypted_blob=base64.b64encode(msg_orm.encrypted_blob).decode() if msg_orm.encrypted_blob else None,
                sender_encrypted_blob=base64.b64encode(msg_orm.sender_encrypted_blob).decode() if msg_orm.sender_encrypted_blob else None,
                signature=base64.b64encode(msg_orm.signature).decode() if msg_orm.signature else None,
                recipient_id=msg_orm.recipient_id,
                created_at=msg_orm.created_at,
                files=message_files,
            )
        )

    return message_responses


async def send_encrypted_message(
    db: AsyncSession,
    sender_id: int,
    recipient_username: str,
    room_id: int,
    encrypted_blob: bytes,
    sender_encrypted_blob: bytes,
    signature: bytes,
    file_ids: list[int] | None = None,
) -> SendMessageResponse:
    """Persist and deliver an E2EE message. Raises HTTPException on failure."""
    # 1. Resolve recipient by username
    result = await db.execute(select(User).where(User.username == recipient_username))
    recipient = result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found")

    # 2. Verify sender is a member of the room
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == sender_id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    # 3. Persist the encrypted message
    msg = Message(
        room_id=room_id,
        author_id=sender_id,
        encrypted_blob=encrypted_blob,
        sender_encrypted_blob=sender_encrypted_blob,
        signature=signature,
        recipient_id=recipient.id,
        is_encrypted=True,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # Associate uploaded files with this message
    if file_ids:
        from app.models.file import File
        for fid in file_ids:
            file_orm = await db.get(File, fid)
            if file_orm and file_orm.room_id == room_id:
                file_orm.message_id = msg.id
        await db.commit()
        await db.refresh(msg)

    # 4. Attempt WebSocket delivery to recipient — include full encrypted payload
    delivered = False
    try:
        # Also look up sender username for the client
        sender_result = await db.execute(select(User).where(User.id == sender_id))
        sender = sender_result.scalar_one_or_none()
        sender_username = sender.username if sender else str(sender_id)

        # Load associated files for the WS payload
        from app.models.file import File
        from sqlalchemy.orm import selectinload
        msg_with_files = await db.execute(
            select(Message).options(selectinload(Message.files)).where(Message.id == msg.id)
        )
        msg_loaded = msg_with_files.scalar_one()
        files_payload = [
            {"id": f.id, "filename": f.filename, "room_id": f.room_id, "created_at": f.created_at.isoformat()}
            for f in (msg_loaded.files or [])
        ]

        await manager.send_to_user(
            recipient.id,
            {
                "type": "encrypted_message",
                "payload": {
                    "message_id": msg.id,
                    "sender_id": sender_id,
                    "sender_username": sender_username,
                    "room_id": room_id,
                    "encrypted_blob": base64.b64encode(encrypted_blob).decode(),
                    "sender_encrypted_blob": base64.b64encode(sender_encrypted_blob).decode(),
                    "signature": base64.b64encode(signature).decode(),
                    "is_encrypted": True,
                    "created_at": msg.created_at.isoformat(),
                    "files": files_payload,
                },
            },
        )
        delivered = True
    except Exception:
        delivered = False

    # 5. If delivered, stamp delivered_at and commit
    if delivered:
        msg.delivered_at = datetime.now(timezone.utc)
        await db.commit()

    return SendMessageResponse(
        message_id=msg.id,
        created_at=msg.created_at,
        delivered=delivered,
    )
