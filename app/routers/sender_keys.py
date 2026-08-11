"""HTTP surface for group E2EE (sender keys).

Every endpoint here is room-scoped and membership-checked in the service
layer. The server only ever moves ciphertext: bundles carry chain keys already
encrypted with the pairwise ratchet, and group messages are opaque v3 blobs.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.messages import SendMessageResponse
from app.schemas.sender_keys import (
    SendGroupMessageRequest,
    SenderKeyBundleResponse,
    SenderKeyDistributionRequest,
    SenderKeyDistributionResponse,
    SenderKeyStateResponse,
)
from app.services.sender_key_service import (
    fetch_bundles,
    get_key_state,
    send_group_message,
    store_distributions,
)

router = APIRouter(tags=["sender-keys"])

MAX_GROUP_BLOB_BYTES = 256 * 1024


def _decode(value: str, field: str, limit: int = MAX_GROUP_BLOB_BYTES) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field} is not valid base64")
    if not raw:
        raise HTTPException(status_code=400, detail=f"{field} must not be empty")
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"{field} is too large")
    return raw


@router.get(
    "/rooms/{room_id}/sender-keys/state", response_model=SenderKeyStateResponse
)
async def read_key_state(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SenderKeyStateResponse:
    """Current membership generation + member handles for a room."""
    return await get_key_state(db, room_id, current_user)


@router.post(
    "/rooms/{room_id}/sender-keys",
    response_model=SenderKeyDistributionResponse,
    status_code=201,
)
async def distribute_sender_key(
    room_id: int,
    body: SenderKeyDistributionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SenderKeyDistributionResponse:
    """Upload one pairwise-encrypted copy of my sender chain per member."""
    return await store_distributions(
        db,
        room_id=room_id,
        sender=current_user,
        chain_id=body.chain_id,
        key_epoch=body.key_epoch,
        bundles=body.bundles,
    )


@router.get("/sender-keys", response_model=list[SenderKeyBundleResponse])
async def read_pending_sender_keys(
    room_id: int | None = Query(default=None),
    include_delivered: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SenderKeyBundleResponse]:
    """Catch-up fetch of chain bundles addressed to me."""
    return await fetch_bundles(
        db,
        current_user,
        room_id=room_id,
        include_delivered=include_delivered,
    )


@router.post(
    "/rooms/{room_id}/group-messages",
    response_model=SendMessageResponse,
    status_code=201,
)
async def send_group_encrypted_message(
    room_id: int,
    body: SendGroupMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    """Send one sender-key (v3) ciphertext to a whole room."""
    return await send_group_message(
        db,
        room_id=room_id,
        sender=current_user,
        encrypted_blob=_decode(body.encrypted_blob, "encrypted_blob"),
        signature=_decode(body.signature, "signature", limit=1024),
        chain_id=body.chain_id,
        key_epoch=body.key_epoch,
        file_ids=body.file_ids,
    )
