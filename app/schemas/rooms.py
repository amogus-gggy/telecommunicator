from pydantic import BaseModel, Field

from app.models.room import RoomType


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    room_type: RoomType = RoomType.PUBLIC
    is_private: bool = False


class RoomResponse(BaseModel):
    id: int
    name: str
    room_type: RoomType
    owner_username: str
    member_count: int
    is_private: bool
    allow_member_invite: bool
    read_only: bool


class PermissionUpdate(BaseModel):
    allow_member_invite: bool | None = None
    read_only: bool | None = None


class PersonalChatRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
