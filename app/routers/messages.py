import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.message import Message
from app.models.user import User
from app.schemas.messages import EncryptedMessageResponse, MessageResponse, SendEncryptedMessageRequest, SendMessageResponse
from app.services.message_service import get_message_history, send_encrypted_message

router = APIRouter(tags=["messages"])


@router.post("/messages", response_model=SendMessageResponse, status_code=201)
async def send_message_encrypted(
    body: SendEncryptedMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    if not body.encrypted_blob:
        raise HTTPException(status_code=400, detail="encrypted_blob is required")
    if not body.signature:
        raise HTTPException(status_code=400, detail="signature is required")

    try:
        encrypted_blob_bytes = base64.b64decode(body.encrypted_blob)
    except Exception:
        raise HTTPException(status_code=400, detail="encrypted_blob is not valid base64")

    try:
        sender_encrypted_blob_bytes = base64.b64decode(body.sender_encrypted_blob)
    except Exception:
        raise HTTPException(status_code=400, detail="sender_encrypted_blob is not valid base64")

    try:
        signature_bytes = base64.b64decode(body.signature)
    except Exception:
        raise HTTPException(status_code=400, detail="signature is not valid base64")

    return await send_encrypted_message(
        db,
        current_user.id,
        body.recipient_username,
        body.room_id,
        encrypted_blob_bytes,
        sender_encrypted_blob_bytes,
        signature_bytes,
    )


@router.get("/messages", response_model=list[EncryptedMessageResponse])
async def get_encrypted_messages(
    room_id: int | None = Query(default=None),
    since: datetime | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EncryptedMessageResponse]:
    # Build query: messages addressed to current user that are encrypted
    stmt = (
        select(Message, User)
        .join(User, Message.author_id == User.id)
        .where(Message.recipient_id == current_user.id)
        .where(Message.is_encrypted == True)  # noqa: E712
    )
    if room_id is not None:
        stmt = stmt.where(Message.room_id == room_id)
    if since is not None:
        stmt = stmt.where(Message.created_at > since)
    stmt = stmt.order_by(Message.created_at.asc())

    result = await db.execute(stmt)
    rows = result.all()

    responses: list[EncryptedMessageResponse] = []
    for msg, sender in rows:
        # Mark as delivered
        msg.delivered_at = datetime.now(timezone.utc)
        responses.append(
            EncryptedMessageResponse(
                message_id=msg.id,
                sender_id=sender.id,
                sender_username=sender.username,
                encrypted_blob=base64.b64encode(msg.encrypted_blob).decode() if msg.encrypted_blob else "",
                signature=base64.b64encode(msg.signature).decode() if msg.signature else "",
                created_at=msg.created_at,
            )
        )

    if rows:
        await db.commit()

    return responses


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.recipient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this message")
    await db.delete(msg)
    await db.commit()


@router.get("/rooms/{room_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    room_id: int,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    return await get_message_history(
        room_id=room_id,
        user=current_user,
        db=db,
        before_id=before_id,
        limit=limit,
    )
