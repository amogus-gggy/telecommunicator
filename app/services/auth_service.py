import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

SECRET_KEY: str = os.getenv(
    "SECRET_KEY", "dev-fallback-secret-key-change-in-production"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


async def register_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
    identity_pub_ed25519: bytes,
    identity_pub_x25519: bytes,
    encrypted_backup: bytes,
) -> User:
    """Register a new user with E2EE public keys. Raises 409 on duplicate, 400 on invalid keys."""
    from fastapi import HTTPException

    # Validate public key sizes
    if len(identity_pub_ed25519) != 32:
        raise HTTPException(
            status_code=400, detail="identity_pub_ed25519 must be exactly 32 bytes"
        )
    if len(identity_pub_x25519) != 32:
        raise HTTPException(
            status_code=400, detail="identity_pub_x25519 must be exactly 32 bytes"
        )

    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already exists")

    hashed_password = _hash_password(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        identity_pub_ed25519=identity_pub_ed25519,
        identity_pub_x25519=identity_pub_x25519,
        encrypted_backup=encrypted_backup,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User:
    """Authenticate a user. Raises 401 HTTPException on failure (generic message)."""
    from fastapi import HTTPException

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not _verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return user


def create_access_token(
    user_id: int, username: str, expire_hours: int = ACCESS_TOKEN_EXPIRE_HOURS
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises on expiry or invalid token."""
    from fastapi import HTTPException

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated")
