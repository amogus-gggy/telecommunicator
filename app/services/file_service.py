from __future__ import annotations

import os
import uuid
import traceback
from typing import AsyncIterator
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.file import File
from app.models.room_member import RoomMember
from app.config import get_config

# Get config-driven values
_config = get_config()
UPLOAD_DIR = _config.upload_dir
MAX_FILE_SIZE = _config.get_max_file_size_bytes()


async def upload_file_stream(
    room_id: int,
    user,
    filename: str,
    stream: AsyncIterator[bytes],
    db: AsyncSession,
    key_blob: str | None = None,
    key_sender_blob: str | None = None,
    key_signature: str | None = None,
):
    """Stream request body directly to disk — no multipart, no Starlette buffering."""
    # Check file extension
    if not _config.is_extension_allowed(filename):
        raise HTTPException(400, f"File type not allowed: {Path(filename).suffix}")

    # Check if file uploads are enabled
    if not _config.allow_file_uploads:
        raise HTTPException(403, "File uploads are disabled on this server")

    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(403, "Not a member")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_name = f"{uuid.uuid4()}_{filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    print(f"[UPLOAD] Streaming: {filename} -> {file_path}")

    try:
        total_size = 0
        with open(file_path, "wb") as f:
            async for chunk in stream:
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    f.close()
                    os.remove(file_path)
                    max_mb = _config.limits.file_upload.max_file_size_mb
                    raise HTTPException(413, f"File too large (max {max_mb} MB)")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        traceback.print_exc()
        raise HTTPException(500, "Failed to save file")

    print(f"[UPLOAD] Saved {total_size} bytes")

    db_file = File(
        filename=filename,
        path=file_path,
        uploader_id=user.id,
        room_id=room_id,
        is_encrypted=key_blob is not None,
        key_blob=key_blob,
        key_sender_blob=key_sender_blob,
        key_signature=key_signature,
    )
    db.add(db_file)
    try:
        await db.commit()
        await db.refresh(db_file)
    except Exception:
        await db.rollback()
        traceback.print_exc()
        raise HTTPException(500, "Database error while saving file")

    print(f"[UPLOAD] File saved (id={db_file.id})")
    return db_file


async def list_files(room_id: int, user, db: AsyncSession):
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(403, "Not a member")

    result = await db.execute(select(File).where(File.room_id == room_id))
    return result.scalars().all()


async def get_file(file_id: int, user, db: AsyncSession) -> File:
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(404, "File not found")

    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == file.room_id,
            RoomMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(403, "Not allowed")

    return file
