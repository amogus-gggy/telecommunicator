from pydantic import BaseModel, ConfigDict
from datetime import datetime

class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploader_id: int
    room_id: int
    created_at: datetime