from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploader_id: int
    room_id: int
    created_at: datetime
    is_encrypted: bool = False
    key_blob: Optional[str] = None
    key_sender_blob: Optional[str] = None
    key_signature: Optional[str] = None


class EncryptedFileUpload(BaseModel):
    """Metadata sent alongside an encrypted file upload."""

    key_blob: str
    key_sender_blob: str
    key_signature: str
