"""Real WebSocket round-trip: does the sender's own socket receive the
encrypted_message frame WITH files?"""

import base64
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.db.base import Base
from app.db.deps import get_db
from app.routers import auth as auth_router
from app.routers import rooms as rooms_router
from app.routers import messages as messages_router
from app.routers import users as users_router
from app.routers import ws as ws_router
from app.services.rate_limit import limiter

limiter.enabled = False


@pytest.fixture
async def app_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(app_engine) -> AsyncGenerator[AsyncClient, None]:
    session_maker = async_sessionmaker(app_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    test_app = FastAPI(lifespan=noop_lifespan)
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.include_router(auth_router.router)
    test_app.include_router(rooms_router.router)
    test_app.include_router(messages_router.router)
    test_app.include_router(users_router.router)
    test_app.include_router(ws_router.router)
    test_app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


async def register_and_login(client, username, email, password):
    await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "identity_pub_ed25519": base64.b64encode(b"\x01" * 32).decode(),
            "identity_pub_x25519": base64.b64encode(b"\x02" * 32).decode(),
            "encrypted_backup": base64.b64encode(b"\x03" * 64).decode(),
        },
    )
    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    return resp.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_sender_receives_own_broadcast_with_files(client):
    alice = await register_and_login(client, "alice_ws", "alice_ws@x.com", "password123")
    bob = await register_and_login(client, "bob_ws", "bob_ws@x.com", "password123")

    resp = await client.post("/rooms", json={"name": "ws-room"}, headers=auth(alice))
    room_id = resp.json()["id"]
    await client.post(f"/rooms/{room_id}/members", json={"username": "bob_ws"}, headers=auth(alice))
    await client.post(f"/rooms/{room_id}/join", headers=auth(bob))

    # alice uploads a file
    resp = await client.post(
        f"/rooms/{room_id}/files",
        headers={**auth(alice), "X-Filename": "photo.png", "Content-Type": "application/octet-stream"},
        content=b"fake-png-bytes",
    )
    file_id = resp.json()["id"]

    # Connect alice's websocket to the room
    from starlette.testclient import TestClient
    from app.main import app

    # Use a lightweight ASGI app that mirrors `client` but with WS support
    session_maker = async_sessionmaker(AsyncSession)

    # Instead: build a TestClient from the same test_app we can't easily share.
    # Simpler: use the ASGITransport app + websocket via httpx is not supported,
    # so spin a real uvicorn? No. We'll test the manager broadcast directly.

    from app.ws.connection_manager import manager

    # Register a fake socket to capture what broadcast sends
    class FakeWs:
        def __init__(self):
            self.received = []

        async def send_json(self, payload):
            self.received.append(payload)

    fake = FakeWs()
    await manager.connect(room_id, fake, 1)  # user_id=1 is alice

    # Now send an encrypted group message with file_ids
    resp = await client.post(
        "/messages",
        json={
            "room_id": room_id,
            "recipient_username": None,
            "encrypted_blob": base64.b64encode(b"blob").decode(),
            "sender_encrypted_blob": base64.b64encode(b"senderblob").decode(),
            "signature": base64.b64encode(b"sig").decode(),
            "file_ids": [file_id],
        },
        headers=auth(alice),
    )
    assert resp.status_code == 201

    # The fake socket (representing alice's own connection) should have received it
    assert fake.received, "alice's socket did not receive any broadcast!"
    frame = fake.received[0]
    print("ALICE WS FRAME:", json.dumps(frame, default=str))
    assert frame["type"] == "encrypted_message"
    payload = frame["payload"]
    print("ALICE FRAME files:", payload.get("files"))
    assert payload.get("files"), "alice's own broadcast frame has NO files!"
    print("PASS: alice receives own broadcast with files")