from typing import Any, Literal

from pydantic import BaseModel, Field


class FederationHelloRequest(BaseModel):
    server_name: str


class FederationHelloResponse(BaseModel):
    server_name: str
    base_url: str
    public_key: str | None = None


class FederationUserLookupRequest(BaseModel):
    username: str


class FederationUserLookupResponse(BaseModel):
    found: bool
    username: str | None = None
    server_name: str | None = None
    display_name: str | None = None
    identity_pub_ed25519: str | None = None
    identity_pub_x25519: str | None = None


class FederationMember(BaseModel):
    username: str
    server_name: str
    display_name: str | None = None
    identity_pub_ed25519: str | None = None
    identity_pub_x25519: str | None = None


class FederationRoomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    room_type: Literal["personal", "group", "public"] = "group"
    is_private: bool = False
    members: list[FederationMember] = []


class FederationRoomCreateResponse(BaseModel):
    room_id: int
    name: str
    room_type: str
    is_private: bool
    owner: FederationMember | None = None
    members: list[FederationMember] = []


class FederationRoomImportRequest(BaseModel):
    remote_room_id: int
    name: str = Field(min_length=1, max_length=64)
    room_type: Literal["personal", "group", "public"] = "group"
    is_private: bool = False
    owner: FederationMember | None = None
    members: list[FederationMember] = []


class FederationRoomImportResponse(BaseModel):
    local_room_id: int
    remote_room_id: int


class FederationRoomMessage(BaseModel):
    sender: FederationMember
    payload: dict[str, Any]


class FederationJoinRequest(BaseModel):
    user: FederationMember
