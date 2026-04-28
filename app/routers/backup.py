import base64

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.backup import BackupResponse, BackupUpdateRequest

router = APIRouter(prefix="/backup", tags=["backup"])


@router.put("", status_code=200)
async def update_backup(
    body: BackupUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store an encrypted key backup for the authenticated user. Requirements: 2.5, 19.2, 19.4"""
    try:
        decoded = base64.b64decode(body.encrypted_backup)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")

    current_user.encrypted_backup = decoded
    current_user.backup_version = (current_user.backup_version or 0) + 1
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return {"success": True, "backup_version": current_user.backup_version}


@router.get("", response_model=BackupResponse)
async def get_backup(
    current_user: User = Depends(get_current_user),
):
    """Retrieve the encrypted key backup for the authenticated user. Requirements: 3.2, 19.5"""
    if current_user.encrypted_backup is None:
        raise HTTPException(status_code=404, detail="No backup found")

    return BackupResponse(
        encrypted_backup=base64.b64encode(current_user.encrypted_backup).decode(),
        backup_version=current_user.backup_version,
    )
