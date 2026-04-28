from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.rooms import (
    PermissionUpdate,
    RoomCreate,
    RoomResponse,
    PersonalChatRequest,
)
from app.services import room_service, file_service
from app.schemas.files import FileResponse

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=RoomResponse, status_code=201)
async def create_room(
    data: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.create_room(data, current_user, db)


@router.get("", response_model=list[RoomResponse])
async def list_rooms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoomResponse]:
    return await room_service.list_public_rooms(db)


@router.get("/my", response_model=list[RoomResponse])
async def get_my_chats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoomResponse]:
    return await room_service.get_user_chats(current_user, db)


@router.post("/personal", response_model=RoomResponse, status_code=201)
async def create_personal_chat(
    data: PersonalChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.create_personal_chat(data.username, current_user, db)


@router.post("/{room_id}/join", response_model=RoomResponse)
async def join_room(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.join_room(room_id, current_user, db)


@router.post("/{room_id}/leave", response_model=RoomResponse)
async def leave_room(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.leave_room(room_id, current_user, db)


@router.post("/{room_id}/invite/{username}", response_model=RoomResponse)
async def invite_user(
    room_id: int,
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.invite_user(room_id, username, current_user, db)


@router.delete("/{room_id}/members/{username}", response_model=RoomResponse)
async def remove_member(
    room_id: int,
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.remove_member(room_id, username, current_user, db)


@router.patch("/{room_id}/permissions", response_model=RoomResponse)
async def update_permissions(
    room_id: int,
    data: PermissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomResponse:
    return await room_service.update_permissions(room_id, data, current_user, db)


@router.get("/{room_id}/files", response_model=list[FileResponse])
async def list_files(
    room_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await file_service.list_files(room_id, user, db)


@router.post("/{room_id}/files", response_model=FileResponse)
async def upload_file(
    room_id: int,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream-upload a file without multipart buffering.

    Metadata via headers:
      X-Filename        — original filename (required)
      X-Key-Blob        — base64 E2EE recipient key blob (optional)
      X-Key-Sender-Blob — base64 E2EE sender key blob (optional)
      X-Key-Signature   — base64 Ed25519 signature (optional)
    """
    filename = request.headers.get("X-Filename", "").strip()
    if not filename:
        raise HTTPException(400, "X-Filename header is required")

    return await file_service.upload_file_stream(
        room_id=room_id,
        user=user,
        filename=filename,
        stream=request.stream(),
        db=db,
        key_blob=request.headers.get("X-Key-Blob") or None,
        key_sender_blob=request.headers.get("X-Key-Sender-Blob") or None,
        key_signature=request.headers.get("X-Key-Signature") or None,
    )


@router.get("/{room_id}/files/{file_id}/download")
async def download_file(
    room_id: int,
    file_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file = await file_service.get_file(file_id, user, db)

    if file.room_id != room_id:
        raise HTTPException(404)

    return FastAPIFileResponse(
        file.path, filename=file.filename, media_type="application/octet-stream"
    )
