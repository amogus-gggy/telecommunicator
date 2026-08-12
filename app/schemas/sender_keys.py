from pydantic import BaseModel, Field


class SenderKeyEntry(BaseModel):
    """One distribution blob addressed to a single room member."""

    recipient_username: str
    generation: int = Field(ge=0)
    blob: str = Field(min_length=1)


class SenderKeysUploadRequest(BaseModel):
    entries: list[SenderKeyEntry]


class SenderKeysUploadResponse(BaseModel):
    stored: int


class SenderKeyBlob(BaseModel):
    sender_username: str
    generation: int
    blob: str


class SenderKeysResponse(BaseModel):
    room_id: int
    keys: list[SenderKeyBlob] = []
