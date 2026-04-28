from pydantic import BaseModel


class BackupUpdateRequest(BaseModel):
    encrypted_backup: str  # base64-encoded encrypted backup


class BackupResponse(BaseModel):
    encrypted_backup: str
    backup_version: int

    model_config = {"from_attributes": True}
