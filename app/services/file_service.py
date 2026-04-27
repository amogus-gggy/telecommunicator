from __future__ import annotations

import os
import uuid
import traceback

from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.file import File
from app.models.room_member import RoomMember

UPLOAD_DIR = "uploads"


async def upload_file(room_id: int, user, file: UploadFile, db: AsyncSession):
    try:
        # Validate input
        if file is None:
            raise HTTPException(400, "No file provided")

        if not file.filename:
            raise HTTPException(400, "Filename is missing")

        # Check membership
        membership = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id == user.id
            )
        )
        if membership.scalar_one_or_none() is None:
            raise HTTPException(403, "Not a member")

        # Ensure upload dir exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # Generate unique filename
        unique_name = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, unique_name)

        print(f"[UPLOAD] Receiving file: {file.filename}")
        print(f"[UPLOAD] Saving to: {file_path}")

        # Save file
        try:
            with open(file_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1MB
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception:
            print("[UPLOAD ERROR] Failed during file write:")
            traceback.print_exc()
            raise HTTPException(500, "Failed to save file")

        # ---- Store in DB ----
        db_file = File(
            filename=file.filename,
            path=file_path,
            uploader_id=user.id,
            room_id=room_id
        )

        db.add(db_file)

        try:
            await db.commit()
            await db.refresh(db_file)
        except Exception:
            await db.rollback()
            print("[UPLOAD ERROR] DB commit failed:")
            traceback.print_exc()
            raise HTTPException(500, "Database error while saving file")

        print(f"[UPLOAD] File saved successfully (id={db_file.id})")

        return db_file

    except HTTPException:
        # rethrow clean API errors
        raise

    except Exception:
        print("[UPLOAD ERROR] Unexpected exception:")
        traceback.print_exc()
        raise HTTPException(500, "Internal server error")


async def list_files(room_id: int, user, db: AsyncSession):
    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user.id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(403, "Not a member")

    result = await db.execute(
        select(File).where(File.room_id == room_id)
    )
    return result.scalars().all()


async def get_file(file_id: int, user, db: AsyncSession) -> File:
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(404, "File not found")

    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == file.room_id,
            RoomMember.user_id == user.id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(403, "Not allowed")

    return file