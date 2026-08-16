"""Temporary reproduction for the attachment bug."""

import base64
import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.message import Message


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
async def test_repro_encrypted_group_file(client: AsyncClient, test_db: AsyncSession):
    alice = await register_and_login(client, "alice_f", "alice_f@x.com", "password123")
    bob = await register_and_login(client, "bob_f", "bob_f@x.com", "password123")

    # alice creates a group room and invites bob
    resp = await client.post("/rooms", json={"name": "repro-room"}, headers=auth(alice))
    room_id = resp.json()["id"]
    await client.post(f"/rooms/{room_id}/members", json={"username": "bob_f"}, headers=auth(alice))

    # bob joins
    await client.post(f"/rooms/{room_id}/join", headers=auth(bob))

    # alice uploads a file (group-encrypted upload = no key_blob)
    resp = await client.post(
        f"/rooms/{room_id}/files",
        headers={**auth(alice), "X-Filename": "photo.png", "Content-Type": "application/octet-stream"},
        content=b"fake-png-bytes",
    )
    assert resp.status_code == 200, resp.text
    file_meta = resp.json()
    print("UPLOAD RESPONSE:", file_meta)

    file_id = file_meta["id"]

    # alice sends a group encrypted message referencing the file
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
    print("SEND RESPONSE:", resp.status_code, resp.text)
    assert resp.status_code == 201

    # inspect DB association
    f = await test_db.get(File, file_id)
    print("FILE ORM message_id:", f.message_id)
    assert f.message_id is not None

    # history should include the file
    resp = await client.get(f"/rooms/{room_id}/messages", headers=auth(alice))
    msgs = resp.json()
    print("HISTORY:", msgs)
    assert len(msgs) == 1
    assert len(msgs[0]["files"]) == 1
    print("HISTORY FILE:", msgs[0]["files"][0])

    # Now capture the broadcast frame the sender's socket would receive
    from app.ws.connection_manager import manager

    captured = {}

    async def fake_broadcast(rid, frame):
        captured["frame"] = frame

    original = manager.broadcast
    manager.broadcast = fake_broadcast
    try:
        resp = await client.post(
            "/messages",
            json={
                "room_id": room_id,
                "recipient_username": None,
                "encrypted_blob": base64.b64encode(b"blob2").decode(),
                "sender_encrypted_blob": base64.b64encode(b"senderblob2").decode(),
                "signature": base64.b64encode(b"sig2").decode(),
                "file_ids": [file_id],
            },
            headers=auth(alice),
        )
        assert resp.status_code == 201
    finally:
        manager.broadcast = original

    frame = captured["frame"]
    print("BROADCAST FRAME PAYLOAD:", json.dumps(frame.get("payload", {}), default=str))
    assert frame["payload"]["files"], "files should be in broadcast frame"