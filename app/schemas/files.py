from pydantic import BaseModel
from datetime import datetime

class FileResponse(BaseModel):
    id: int
    filename: str
    uploader_id: int
    room_id: int
    created_at: datetime

    class Config:
        from_attributes = True