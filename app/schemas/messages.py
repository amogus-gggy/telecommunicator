from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: int
    room_id: int
    author_username: str
    author_display_name: str | None = None
    body: str
    created_at: datetime
    files: list[dict] | None = None


class WsInbound(BaseModel):
    type: Literal["message"]
    room_id: int
    body: str
    files: list[dict] | None = None


class WsOutbound(BaseModel):
    type: Literal["message", "error"]
    payload: MessageResponse | str
