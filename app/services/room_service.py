from fastapi import HTTPException
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Room, RoomType
from app.models.room_member import RoomMember
from app.models.user import User
from app.schemas.rooms import PermissionUpdate, RoomCreate, RoomResponse
from app.ws.connection_manager import manager as ws_manager


def _build_response(room: Room, owner_username: str, member_count: int) -> RoomResponse:
    return RoomResponse(
        id=room.id,
        name=room.name,
        room_type=room.room_type,
        owner_username=owner_username,
        member_count=member_count,
        is_private=room.is_private,
        allow_member_invite=room.allow_member_invite,
        read_only=room.read_only,
    )


async def _room_to_response(room: Room, db: AsyncSession) -> RoomResponse:
    """Single-room response — used after mutations where we already have the room."""
    owner = await db.get(User, room.owner_id)
    count_result = await db.execute(
        select(func.count()).where(RoomMember.room_id == room.id)
    )
    member_count = count_result.scalar_one()
    return _build_response(room, owner.username if owner else "", member_count)


async def _rooms_to_responses(rooms: list[Room], db: AsyncSession) -> list[RoomResponse]:
    """Batch-load owners and member counts for a list of rooms — avoids N+1."""
    if not rooms:
        return []

    room_ids = [r.id for r in rooms]
    owner_ids = list({r.owner_id for r in rooms})

    # Single query for all owners
    owner_rows = await db.execute(select(User).where(User.id.in_(owner_ids)))
    owner_map: dict[int, str] = {u.id: u.username for u in owner_rows.scalars()}

    # Single query for all member counts
    count_rows = await db.execute(
        select(RoomMember.room_id, func.count().label("cnt"))
        .where(RoomMember.room_id.in_(room_ids))
        .group_by(RoomMember.room_id)
    )
    count_map: dict[int, int] = {row.room_id: row.cnt for row in count_rows}

    return [
        _build_response(r, owner_map.get(r.owner_id, ""), count_map.get(r.id, 0))
        for r in rooms
    ]


async def create_room(data: RoomCreate, owner: User, db: AsyncSession) -> RoomResponse:
    # Для публичных комнат проверяем уникальность имени
    if data.room_type == "public":
        existing = await db.execute(select(Room).where(Room.name == data.name))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Room name already exists")

    room = Room(
        name=data.name, 
        room_type=data.room_type,
        owner_id=owner.id, 
        is_private=data.is_private
    )
    db.add(room)
    await db.flush()

    member = RoomMember(room_id=room.id, user_id=owner.id)
    db.add(member)
    await db.commit()
    await db.refresh(room)

    return _build_response(room, owner.username, 1)


async def list_public_rooms(db: AsyncSession) -> list[RoomResponse]:
    result = await db.execute(
        select(Room).where(
            Room.is_private == False,  # noqa: E712
            Room.room_type == "public"
        )
    )
    rooms = result.scalars().all()
    return await _rooms_to_responses(list(rooms), db)


async def join_room(room_id: int, user: User, db: AsyncSession) -> RoomResponse:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    # Single membership query covers both the private-room gate and idempotency check
    existing = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    is_member = existing.scalar_one_or_none() is not None

    if room.is_private and not is_member:
        raise HTTPException(status_code=403, detail="Cannot join a private room without an invite")

    # Track if this is a first-time join for notification purposes
    is_first_time_join = False

    if not is_member:
        # Only group and public rooms trigger join notifications
        if room.room_type in ("group", "public"):
            is_first_time_join = True
        db.add(RoomMember(room_id=room_id, user_id=user.id))
        await db.commit()

    # Send first-time join notification to existing members
    if is_first_time_join:
        # Query all existing members excluding the new joiner
        members_result = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id != user.id,
            )
        )
        existing_members = members_result.scalars().all()

        # Get the new member's join timestamp
        new_member_result = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id == user.id,
            )
        )
        new_member = new_member_result.scalar_one()

        for member in existing_members:
            try:
                await ws_manager.send_to_user(member.user_id, {
                    "type": "member_joined",
                    "payload": {
                        "room_id": room_id,
                        "room_name": room.name,
                        "username": user.username,
                        "joined_at": new_member.joined_at.isoformat(),
                    },
                })
            except Exception:
                # Notification failure must not block the join operation
                pass

    return await _room_to_response(room, db)


async def leave_room(room_id: int, user: User, db: AsyncSession) -> RoomResponse:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.owner_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="Owner must transfer ownership or delete the room before leaving",
        )

    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    member = membership.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Not a member of this room")

    await db.delete(member)
    await db.commit()

    return await _room_to_response(room, db)


async def invite_user(room_id: int, username: str, requester: User, db: AsyncSession) -> RoomResponse:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    # Permission check: owner can always invite; non-owner only if allow_member_invite
    if room.owner_id != requester.id:
        req_membership = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id, RoomMember.user_id == requester.id
            )
        )
        if req_membership.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not a member of this room")
        if not room.allow_member_invite:
            raise HTTPException(status_code=403, detail="Members are not allowed to invite in this room")

    target_result = await db.execute(select(User).where(User.username == username))
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == target.id
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(RoomMember(room_id=room_id, user_id=target.id))
        await db.commit()

    response = await _room_to_response(room, db)

    # Notify the invited user in real-time if they're connected
    await ws_manager.send_to_user(target.id, {
        "type": "invite",
        "payload": {
            "id": response.id,
            "name": response.name,
            "owner_username": response.owner_username,
            "member_count": response.member_count,
            "is_private": response.is_private,
            "allow_member_invite": response.allow_member_invite,
            "read_only": response.read_only,
        },
    })

    return response


async def remove_member(room_id: int, username: str, requester: User, db: AsyncSession) -> RoomResponse:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.owner_id != requester.id:
        raise HTTPException(status_code=403, detail="Only the owner can remove members")

    target_result = await db.execute(select(User).where(User.username == username))
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == room.owner_id:
        raise HTTPException(status_code=400, detail="Owner cannot be removed from the room")

    membership = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == target.id
        )
    )
    member = membership.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="User is not a member of this room")

    await db.delete(member)
    await db.commit()

    return await _room_to_response(room, db)


async def update_permissions(
    room_id: int, data: PermissionUpdate, requester: User, db: AsyncSession
) -> RoomResponse:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.owner_id != requester.id:
        raise HTTPException(status_code=403, detail="Only the owner can update permissions")

    if data.allow_member_invite is not None:
        room.allow_member_invite = data.allow_member_invite
    if data.read_only is not None:
        room.read_only = data.read_only

    await db.commit()
    await db.refresh(room)

    return await _room_to_response(room, db)


async def create_personal_chat(target_username: str, requester: User, db: AsyncSession) -> RoomResponse:
    """Создает или находит существующий личный чат между двумя пользователями."""
    # Найти целевого пользователя
    target_result = await db.execute(select(User).where(User.username == target_username))
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    if target.id == requester.id:
        raise HTTPException(status_code=400, detail="Cannot create personal chat with yourself")
    
    # Проверить, существует ли уже личный чат между этими пользователями
    existing_chat = await db.execute(
        select(Room)
        .join(RoomMember, Room.id == RoomMember.room_id)
        .where(
            Room.room_type == RoomType.PERSONAL,
            RoomMember.user_id.in_([requester.id, target.id])
        )
        .group_by(Room.id)
        .having(func.count(RoomMember.user_id) == 2)
    )
    
    existing_room = existing_chat.scalar_one_or_none()
    if existing_room:
        return await _room_to_response(existing_room, db)
    
    # Создать новый личный чат
    chat_name = f"{requester.username}, {target.username}"
    room = Room(
        name=chat_name,
        room_type=RoomType.PERSONAL,
        owner_id=requester.id,
        is_private=True,
        allow_member_invite=False,
        read_only=False
    )
    db.add(room)
    await db.flush()
    
    # Добавить обоих пользователей как участников
    db.add(RoomMember(room_id=room.id, user_id=requester.id))
    db.add(RoomMember(room_id=room.id, user_id=target.id))
    
    await db.commit()
    await db.refresh(room)
    
    return _build_response(room, requester.username, 2)


async def get_user_chats(user: User, db: AsyncSession) -> list[RoomResponse]:
    """Получить все чаты пользователя (личные и групповые)."""
    result = await db.execute(
        select(Room)
        .join(RoomMember, Room.id == RoomMember.room_id)
        .where(RoomMember.user_id == user.id)
        .order_by(Room.created_at.desc())
    )
    rooms = result.scalars().all()
    return await _rooms_to_responses(list(rooms), db)
