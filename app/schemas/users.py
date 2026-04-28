from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    id: int
    username: str
    email: str
    display_name: str | None

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class PublicKeysResponse(BaseModel):
    user_id: int
    username: str
    identity_pub_ed25519: str
    identity_pub_x25519: str

    model_config = {"from_attributes": True}


class UpdatePublicKeysRequest(BaseModel):
    identity_pub_ed25519: str  # base64-encoded 32-byte Ed25519 public key
    identity_pub_x25519: str  # base64-encoded 32-byte X25519 public key
