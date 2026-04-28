import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        ed25519_bytes = base64.b64decode(body.identity_pub_ed25519)
        x25519_bytes = base64.b64decode(body.identity_pub_x25519)
        backup_bytes = base64.b64decode(body.encrypted_backup)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid base64 encoding in key fields"
        )

    user = await register_user(
        db,
        body.username,
        body.email,
        body.password,
        identity_pub_ed25519=ed25519_bytes,
        identity_pub_x25519=x25519_bytes,
        encrypted_backup=backup_bytes,
    )
    token = create_access_token(user.id, user.username)
    return RegisterResponse(
        user_id=user.id, username=user.username, access_token=token, token_type="bearer"
    )


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, body.username, body.password)
    token = create_access_token(user.id, user.username)
    b64_backup = (
        base64.b64encode(user.encrypted_backup).decode()
        if user.encrypted_backup is not None
        else None
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        encrypted_backup=b64_backup,
        user_id=user.id,
        username=user.username,
    )


@router.get("/me", status_code=status.HTTP_200_OK)
async def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username}
