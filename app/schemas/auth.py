from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8)
    identity_pub_ed25519: str  # base64-encoded Ed25519 public key
    identity_pub_x25519: str  # base64-encoded X25519 public key
    encrypted_backup: str  # base64-encoded encrypted key backup


class RegisterResponse(BaseModel):
    user_id: int
    username: str
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    encrypted_backup: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
