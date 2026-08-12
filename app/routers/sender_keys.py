from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.sender_keys import (
    SenderKeysResponse,
    SenderKeysUploadRequest,
    SenderKeysUploadResponse,
)
from app.services import sender_key_service

router = APIRouter(tags=["sender-keys"])


@router.put(
    "/rooms/{room_id}/sender-keys", response_model=SenderKeysUploadResponse
)
async def upload_sender_keys(
    room_id: int,
    body: SenderKeysUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SenderKeysUploadResponse:
    stored = await sender_key_service.upsert_sender_keys(
        db, room_id, current_user, body.entries
    )
    return SenderKeysUploadResponse(stored=stored)


@router.get("/rooms/{room_id}/sender-keys", response_model=SenderKeysResponse)
async def get_sender_keys(
    room_id: int,
    sender: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SenderKeysResponse:
    return await sender_key_service.get_sender_keys(
        db, room_id, current_user, sender_handle=sender
    )
