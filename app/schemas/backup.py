from pydantic import BaseModel, field_validator

# Maximum size of an encrypted backup (in bytes) once base64-decoded.
MAX_BACKUP_BYTES = 1_048_576  # 1 MiB


class BackupUpdateRequest(BaseModel):
    encrypted_backup: str  # base64-encoded encrypted backup

    @field_validator("encrypted_backup")
    @classmethod
    def _limit_backup_size(cls, value: str) -> str:
        # Coarse pre-filter: reject the request before any decode work when the
        # encoded payload is clearly too large. Base64 expands by 4/3, so use
        # that ceiling. The exact decoded size is enforced in the router.
        max_encoded_len = (MAX_BACKUP_BYTES * 4 // 3) + 4
        if len(value) > max_encoded_len:
            raise ValueError(
                f"Backup too large: exceeds {MAX_BACKUP_BYTES} bytes limit"
            )
        return value


class BackupResponse(BaseModel):
    encrypted_backup: str
    backup_version: int

    model_config = {"from_attributes": True}