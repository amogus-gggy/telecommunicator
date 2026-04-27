from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: int
    room_id: int
    author_username: str
    author_display_name: str | None = None
    body: str | None = None
    is_encrypted: bool = False
    encrypted_blob: str | None = None
    signature: str | None = None
    created_at: datetime
    files: list[dict] | None = None


class SendEncryptedMessageRequest(BaseModel):
    room_id: int
    recipient_username: str
    encrypted_blob: str
    signature: str


class SendMessageResponse(BaseModel):
    message_id: int
    created_at: datetime
    delivered: bool


class EncryptedMessageResponse(BaseModel):
    message_id: int
    sender_id: int
    sender_username: str
    encrypted_blob: str
    signature: str
    created_at: datetime


class WsInbound(BaseModel):
    type: Literal["message"]
    room_id: int
    body: str
    files: list[dict] | None = None


class WsOutbound(BaseModel):
    type: Literal["message", "error"]
    payload: MessageResponse | str
