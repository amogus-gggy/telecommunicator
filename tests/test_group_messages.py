import base64
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ED25519_PUB_B64 = lambda k: base64.b64encode(k.public_key().public_bytes_raw()).decode()
_X25519_PUB_B64 = lambda: base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


async def register_and_login(client: AsyncClient, username: str, email: str, password: str, ed_priv=None):
    if ed_priv is None:
        ed_priv = Ed25519PrivateKey.generate()
    ed_pub_b64 = base64.b64encode(ed_priv.public_key().public_bytes_raw()).decode()
    await client.post("/auth/register", json={
        "username": username, "email": email, "password": password,
        "identity_pub_ed25519": ed_pub_b64,
        "identity_pub_x25519": _X25519_PUB_B64(),
        "encrypted_backup": _BACKUP_B64,
    })
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"], ed_priv

def auth(t): return {"Authorization": f"Bearer {t}"}

async def create_group(client, token, name="grp"):
    r = await client.post("/rooms", json={"name": name, "room_type": "group", "is_private": False}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_group_encrypted_roundtrip(client: AsyncClient, test_db: AsyncSession):
    from client.crypto.sender_keys import GroupSenderKeyManager
    token_alice, ed_alice = await register_and_login(client, "g_alice", "g_alice@example.com", "password123")
    token_bob, _ = await register_and_login(client, "g_bob", "g_bob@example.com", "password123")
    room_id = await create_group(client, token_alice, "grp1")
    # invite bob
    await client.post(f"/rooms/{room_id}/invite/g_bob", headers=auth(token_alice))
    # alice sends group message via sender keys
    mgr_alice = GroupSenderKeyManager()
    # need alice user id for sender_id; fetch me
    me = (await client.get("/users/me", headers=auth(token_alice))).json()
    enc = mgr_alice.encrypt(room_id, "hello group", str(me["id"]), ed_alice)
    resp = await client.post("/messages/group", json={"room_id": room_id, "encrypted_blob": enc["blob"], "signature": enc["signature"]}, headers=auth(token_alice))
    assert resp.status_code == 201, resp.text
    # history visible to bob
    hist = (await client.get(f"/rooms/{room_id}/messages", headers=auth(token_bob))).json()
    assert len(hist) == 1
    assert hist[0]["is_encrypted"] is True
    # bob decrypts
    mgr_bob = GroupSenderKeyManager()
    # simulate distribution: copy chain
    cur = mgr_alice._outgoing[room_id]
    mgr_bob.seed_incoming_chain(room_id, str(me["id"]), cur.chain_id, cur.initial_key)
    assert mgr_bob.decrypt(hist[0]["encrypted_blob"], hist[0]["signature"], ed_alice.public_key()) == "hello group"


@pytest.mark.asyncio
async def test_group_non_member_cannot_send(client: AsyncClient):
    from client.crypto.sender_keys import GroupSenderKeyManager
    token_alice, ed_alice = await register_and_login(client, "g2_alice", "g2_alice@example.com", "password123")
    token_eve, ed_eve = await register_and_login(client, "g2_eve", "g2_eve@example.com", "password123")
    room_id = await create_group(client, token_alice, "grp2")
    mgr = GroupSenderKeyManager()
    enc = mgr.encrypt(room_id, "hi", "999", ed_eve)
    resp = await client.post("/messages/group", json={"room_id": room_id, "encrypted_blob": enc["blob"], "signature": enc["signature"]}, headers=auth(token_eve))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_group_rotation_persists_history(client: AsyncClient):
    from client.crypto.sender_keys import GroupSenderKeyManager
    token_alice, ed_alice = await register_and_login(client, "g3_alice", "g3_alice@example.com", "password123")
    room_id = await create_group(client, token_alice, "grp3")
    me = (await client.get("/users/me", headers=auth(token_alice))).json()
    mgr = GroupSenderKeyManager()
    # send 101 messages to trigger rotation
    for i in range(101):
        enc = mgr.encrypt(room_id, f"m{i}", str(me["id"]), ed_alice)
        resp = await client.post("/messages/group", json={"room_id": room_id, "encrypted_blob": enc["blob"], "signature": enc["signature"]}, headers=auth(token_alice))
        assert resp.status_code == 201
    assert mgr.rotation_count(room_id) == 1
    hist = (await client.get(f"/rooms/{room_id}/messages?limit=200", headers=auth(token_alice))).json()
    assert len(hist) == 101
    # bob joins later and can decrypt old chain if seeded (history retained)
    token_bob, _ = await register_and_login(client, "g3_bob", "g3_bob@example.com", "password123")
    await client.post(f"/rooms/{room_id}/invite/g3_bob", headers=auth(token_alice))
    # server stores all messages; rotation does not delete old
    hist_bob = (await client.get(f"/rooms/{room_id}/messages?limit=200", headers=auth(token_bob))).json()
    assert len(hist_bob) == 101
