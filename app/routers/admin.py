from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.db.deps import get_db
from app.models.message import Message
from app.models.room import Room
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminStats(BaseModel):
    users: int
    local_users: int
    rooms: int
    messages: int
    server_name: str


class AdminUser(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    is_remote: bool
    display_name: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}


class AdminRoom(BaseModel):
    id: int
    name: str
    room_type: str
    is_private: bool
    owner_username: str | None
    member_count: int


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    local_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_remote == False)  # noqa: E712
        )
    ).scalar_one()
    rooms = (await db.execute(select(func.count()).select_from(Room))).scalar_one()
    messages = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    from app.settings import SERVER_NAME

    return AdminStats(
        users=users,
        local_users=local_users,
        rooms=rooms,
        messages=messages,
        server_name=SERVER_NAME,
    )


@router.get("/users", response_model=list[AdminUser])
async def list_users(
    admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.patch("/users/{user_id}/admin")
async def set_admin(
    user_id: int,
    body: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = bool(body.get("is_admin", False))
    await db.commit()
    return {"id": user.id, "is_admin": user.is_admin}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_remote:
        raise HTTPException(status_code=400, detail="Cannot delete remote users")
    await db.delete(user)
    await db.commit()
    return {"deleted": user_id}


@router.get("/rooms", response_model=list[AdminRoom])
async def list_rooms(
    admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    from app.models.room_member import RoomMember

    result = await db.execute(select(Room).order_by(Room.id))
    rooms = result.scalars().all()
    owners = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    out = []
    for room in rooms:
        count = (
            await db.execute(
                select(func.count())
                .select_from(RoomMember)
                .where(RoomMember.room_id == room.id)
            )
        ).scalar_one()
        owner = owners.get(room.owner_id) if getattr(room, "owner_id", None) else None
        out.append(
            AdminRoom(
                id=room.id,
                name=room.name,
                room_type=room.room_type.value if hasattr(room.room_type, "value") else str(room.room_type),
                is_private=room.is_private,
                owner_username=owner,
                member_count=count,
            )
        )
    return out
