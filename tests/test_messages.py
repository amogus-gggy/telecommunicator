"""Integration tests for the messages layer (Task 8 checkpoint)."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import base64

_ED25519_PUB_B64 = base64.b64encode(b"\x01" * 32).decode()
_X25519_PUB_B64 = base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


async def register_and_login(client: AsyncClient, username: str, email: str, password: str) -> str:
    await client.post("/auth/register", json={
        "username": username, "email": email, "password": password,
        "identity_pub_ed25519": _ED25519_PUB_B64,
        "identity_pub_x25519": _X25519_PUB_B64,
        "encrypted_backup": _BACKUP_B64,
    })
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_room_and_get_id(client: AsyncClient, token: str, name: str) -> int:
    resp = await client.post("/rooms", json={"name": name}, headers=auth(token))
    return resp.json()["id"]


async def insert_messages(db: AsyncSession, room_id: int, author_id: int, count: int) -> list[int]:
    """Insert `count` messages directly into the DB and return their IDs."""
    ids = []
    for i in range(count):
        msg = Message(room_id=room_id, author_id=author_id, body=f"message {i}")
        db.add(msg)
        await db.flush()
        ids.append(msg.id)
    await db.commit()
    return ids


async def get_user_id(client: AsyncClient, token: str) -> int:
    resp = await client.get("/users/me", headers=auth(token))
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_can_get_message_history_200(client: AsyncClient, test_db: AsyncSession):
    token = await register_and_login(client, "msg_alice", "msg_alice@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "msg-room-1")
    user_id = await get_user_id(client, token)

    await insert_messages(test_db, room_id, user_id, 3)

    resp = await client.get(f"/rooms/{room_id}/messages", headers=auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_non_member_cannot_get_message_history_403(client: AsyncClient, test_db: AsyncSession):
    owner_token = await register_and_login(client, "msg_bob", "msg_bob@example.com", "password123")
    outsider_token = await register_and_login(client, "msg_carol", "msg_carol@example.com", "password123")

    room_id = await create_room_and_get_id(client, owner_token, "msg-room-2")

    resp = await client.get(f"/rooms/{room_id}/messages", headers=auth(outsider_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_message_history_before_id_cursor(client: AsyncClient, test_db: AsyncSession):
    token = await register_and_login(client, "msg_dave", "msg_dave@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "msg-room-3")
    user_id = await get_user_id(client, token)

    ids = await insert_messages(test_db, room_id, user_id, 10)
    # Use the 6th message ID as cursor — should only return messages with id < that
    cursor_id = ids[5]

    resp = await client.get(f"/rooms/{room_id}/messages?before_id={cursor_id}", headers=auth(token))
    assert resp.status_code == 200
    returned_ids = [m["id"] for m in resp.json()]
    assert all(mid < cursor_id for mid in returned_ids)


@pytest.mark.asyncio
async def test_message_history_default_limit_50(client: AsyncClient, test_db: AsyncSession):
    token = await register_and_login(client, "msg_eve", "msg_eve@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "msg-room-4")
    user_id = await get_user_id(client, token)

    await insert_messages(test_db, room_id, user_id, 60)

    resp = await client.get(f"/rooms/{room_id}/messages", headers=auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 50


@pytest.mark.asyncio
async def test_message_history_limit_capped_at_200(client: AsyncClient, test_db: AsyncSession):
    token = await register_and_login(client, "msg_frank", "msg_frank@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "msg-room-5")
    user_id = await get_user_id(client, token)

    await insert_messages(test_db, room_id, user_id, 250)

    resp = await client.get(f"/rooms/{room_id}/messages?limit=300", headers=auth(token))
    # limit=300 exceeds max; FastAPI Query(le=200) returns 422
    assert resp.status_code == 422
