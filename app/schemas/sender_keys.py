from datetime import datetime

from pydantic import BaseModel, Field


class SenderKeyBundle(BaseModel):
    """One sender-key chain encrypted for exactly one room member."""

    recipient_username: str = Field(min_length=1, max_length=255)
    # Pairwise Double Ratchet ciphertext of the distribution payload (base64).
    encrypted_blob: str = Field(min_length=1)
    # Ed25519 signature of the sender over ``encrypted_blob`` (base64).
    signature: str = Field(min_length=1)


class SenderKeyDistributionRequest(BaseModel):
    chain_id: str = Field(min_length=1, max_length=64)
    key_epoch: int = Field(ge=1)
    bundles: list[SenderKeyBundle] = Field(min_length=1, max_length=500)


class SenderKeyDistributionResponse(BaseModel):
    stored: int
    skipped: list[str] = []
    key_epoch: int


class SenderKeyBundleResponse(BaseModel):
    id: int
    room_id: int
    sender_id: int
    sender_username: str
    chain_id: str
    key_epoch: int
    encrypted_blob: str
    signature: str
    created_at: datetime


class SenderKeyStateResponse(BaseModel):
    """Everything a client needs to decide whether to rotate before sending."""

    room_id: int
    key_epoch: int
    members: list[str]


class SendGroupMessageRequest(BaseModel):
    """A sender-key (v3) group ciphertext addressed to a whole room."""

    encrypted_blob: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    chain_id: str = Field(min_length=1, max_length=64)
    key_epoch: int = Field(ge=1)
    file_ids: list[int] = []
