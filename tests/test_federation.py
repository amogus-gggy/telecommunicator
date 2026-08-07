"""Tests for the server-to-server federation feature.

The client-facing flow is: every request goes to the server the user is logged
into, which then talks to other homeservers over signed ``/federation``
endpoints. These tests exercise that routing logic and the inbound endpoint.
"""

import base64
import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.remote_room_link import RemoteRoomLink
from app.models.room_member import RoomMember
from app.models.server import Server
from app.models.user import User
from app.services.federation_service import (
    _signature_canonical,
    cache_remote_user,
)

_ED25519_PUB_B64 = base64.b64encode(b"\x01" * 32).decode()
_X25519_PUB_B64 = base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


async def register_and_login(
    client: AsyncClient, username: str, email: str, password: str
) -> str:
    await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "identity_pub_ed25519": _ED25519_PUB_B64,
            "identity_pub_x25519": _X25519_PUB_B64,
            "encrypted_backup": _BACKUP_B64,
        },
    )
    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_room_and_get_id(client: AsyncClient, token: str, name: str) -> int:
    resp = await client.post("/rooms", json={"name": name}, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def get_user_id(client: AsyncClient, token: str) -> int:
    resp = await client.get("/users/me", headers=auth(token))
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Inbound: a remote server relays a message into one of our rooms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_federation_message_is_stored_and_author_resolved(
    client: AsyncClient, test_db: AsyncSession
):
    token = await register_and_login(client, "alice", "alice_fed@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "fed-inbound-room")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    pub = private.public_key().public_bytes_raw()
    test_db.add(
        Server(
            server_name="remote-b",
            base_url="http://remote-b:8000",
            is_local=False,
            public_key=pub,
        )
    )
    await test_db.commit()

    path = f"/federation/rooms/{room_id}/message"
    body = {
        "sender": {"username": "bob", "server_name": "remote-b", "display_name": "Bob"},
        "payload": {"body": "hello from remote-b", "is_encrypted": False},
    }
    raw = json.dumps(body).encode()
    date = datetime.now(timezone.utc).isoformat()
    canonical = _signature_canonical("POST", path, date, raw)
    signature = base64.b64encode(private.sign(canonical.encode())).decode()

    resp = await client.post(
        path,
        content=raw,
        headers={
            "X-Federation-Server": "remote-b",
            "X-Federation-Date": date,
            "X-Federation-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200, resp.text

    res = await test_db.execute(
        select(Message).where(
            Message.room_id == room_id, Message.body == "hello from remote-b"
        )
    )
    msg = res.scalar_one()

    author = await test_db.get(User, msg.author_id)
    assert author.username == "bob"
    assert author.server_name == "remote-b"
    assert author.is_remote is True


@pytest.mark.asyncio
async def test_inbound_federation_message_rejects_bad_signature(
    client: AsyncClient, test_db: AsyncSession
):
    token = await register_and_login(client, "alice2", "alice2_fed@example.com", "password123")
    room_id = await create_room_and_get_id(client, token, "inbound-bad-sig")

    test_db.add(
        Server(
            server_name="known",
            base_url="http://known:8000",
            is_local=False,
            public_key=b"\x00" * 32,
        )
    )
    await test_db.commit()

    path = f"/federation/rooms/{room_id}/message"
    raw = json.dumps(
        {"sender": {"username": "x", "server_name": "known"}, "payload": {"body": "x"}}
    ).encode()
    resp = await client.post(
        path,
        content=raw,
        headers={
            "X-Federation-Server": "known",
            "X-Federation-Date": datetime.now(timezone.utc).isoformat(),
            "X-Federation-Signature": base64.b64encode(b"garbage").decode(),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Outbound: routing from a locally-hosted room to member mirrors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_room_relays_message_to_remote_mirrors_except_author(
    client: AsyncClient, test_db: AsyncSession
):
    import app.services.message_service as ms

    sent = []

    async def fake_ensure_server(db, server_name):
        return Server(
            server_name=server_name, base_url=f"http://{server_name}", is_local=False
        )

    async def fake_send_room_message(
        db, server, room_id_on_server, sender_member, payload
    ):
        sent.append((server.server_name, room_id_on_server, sender_member))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(ms, "ensure_server", fake_ensure_server)
    monkey.setattr(ms, "send_room_message", fake_send_room_message)
    try:
        token = await register_and_login(
            client, "alice3", "alice3_fed@example.com", "password123"
        )
        room_id = await create_room_and_get_id(client, token, "fanout-room")

        bob = await cache_remote_user(test_db, "bob", "remote-b")
        carol = await cache_remote_user(test_db, "carol", "remote-c")
        test_db.add(RoomMember(room_id=room_id, user_id=bob.id))
        test_db.add(RoomMember(room_id=room_id, user_id=carol.id))
        test_db.add(
            RemoteRoomLink(
                room_id=room_id, server_name="remote-b", remote_room_id=7
            )
        )
        test_db.add(
            RemoteRoomLink(
                room_id=room_id, server_name="remote-c", remote_room_id=9
            )
        )
        await test_db.commit()

        local_user = await test_db.execute(
            select(User).where(User.username == "alice3")
        )
        author = local_user.scalar_one()

        # Local host author -> fan out to both mirror servers.
        await ms.send_message(room_id, "hello", author=author, db=test_db)
        servers = sorted({s for s, _, _ in sent})
        assert servers == ["remote-b", "remote-c"]
        sent.clear()

        # A remote author (bob@remote-b) must not be sent back to remote-b.
        bob = await cache_remote_user(test_db, "bob", "remote-b")
        await ms.send_message(room_id, "from bob", author=bob, db=test_db)
        assert sent and all(s != "remote-b" for s, _, _ in sent)
        assert {s for s, _, _ in sent} == {"remote-c"}
    finally:
        monkey.undo()


# ---------------------------------------------------------------------------
# Remote user resolution performs a signed lookup against the remote server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_remote_user_looks_up_and_caches(
    test_db: AsyncSession,
):
    import app.services.federation_service as fs

    calls = []

    async def fake_ensure_server(db, server_name):
        return Server(
            server_name=server_name, base_url=f"http://{server_name}", is_local=False
        )

    async def fake_send_to_server(db, server, method, path, body):
        calls.append((server.server_name, path, body))
        return FakeResponse({"found": True, "username": "bob", "server_name": "remote-b"})

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fs, "ensure_server", fake_ensure_server)
    monkeypatch.setattr(fs, "send_to_server", fake_send_to_server)
    try:
        user = await fs.resolve_user(test_db, "bob@remote-b")
        assert user.username == "bob"
        assert user.server_name == "remote-b"
        assert user.is_remote is True
        assert calls and calls[0][1] == "/federation/user/lookup"
    finally:
        monkeypatch.undo()