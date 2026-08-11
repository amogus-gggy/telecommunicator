"""Integration tests for the group E2EE (sender key) HTTP surface.

Covers the key-state endpoint, bundle distribution (membership filtering,
supersession, stale epochs), catch-up fetches, group message sending, and the
epoch bumps triggered by join / invite / leave / removal.
"""

import base64

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_messages import auth, register_and_login

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BLOB = base64.b64encode(b"pairwise-ratchet-ciphertext").decode()
SIG = base64.b64encode(b"\x05" * 64).decode()


def bundle(recipient: str, blob: str = BLOB, signature: str = SIG) -> dict:
    return {
        "recipient_username": recipient,
        "encrypted_blob": blob,
        "signature": signature,
    }


async def make_group(client: AsyncClient, token: str, name: str) -> int:
    resp = await client.post(
        "/rooms",
        json={"name": name, "room_type": "group", "is_private": False},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def join(client: AsyncClient, token: str, room_id: int) -> None:
    resp = await client.post(f"/rooms/{room_id}/join", headers=auth(token))
    assert resp.status_code == 200, resp.text


async def key_state(client: AsyncClient, token: str, room_id: int) -> dict:
    resp = await client.get(
        f"/rooms/{room_id}/sender-keys/state", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def distribute(
    client: AsyncClient,
    token: str,
    room_id: int,
    bundles: list[dict],
    chain_id: str = "chain-1",
    key_epoch: int | None = None,
):
    if key_epoch is None:
        key_epoch = (await key_state(client, token, room_id))["key_epoch"]
    return await client.post(
        f"/rooms/{room_id}/sender-keys",
        json={"chain_id": chain_id, "key_epoch": key_epoch, "bundles": bundles},
        headers=auth(token),
    )


async def send_group(
    client: AsyncClient,
    token: str,
    room_id: int,
    blob: str = BLOB,
    chain_id: str = "chain-1",
    key_epoch: int | None = None,
    **extra,
):
    if key_epoch is None:
        key_epoch = (await key_state(client, token, room_id))["key_epoch"]
    body = {
        "encrypted_blob": blob,
        "signature": SIG,
        "chain_id": chain_id,
        "key_epoch": key_epoch,
    }
    body.update(extra)
    return await client.post(
        f"/rooms/{room_id}/group-messages", json=body, headers=auth(token)
    )


@pytest.fixture
async def trio(client: AsyncClient):
    """A group room with alice (owner), bob and carol."""
    alice = await register_and_login(client, "sk_alice", "sk_alice@e.com", "password123")
    bob = await register_and_login(client, "sk_bob", "sk_bob@e.com", "password123")
    carol = await register_and_login(client, "sk_carol", "sk_carol@e.com", "password123")
    room_id = await make_group(client, alice, "sk-room")
    await join(client, bob, room_id)
    await join(client, carol, room_id)
    return {"alice": alice, "bob": bob, "carol": carol, "room_id": room_id}


# ---------------------------------------------------------------------------
# Key state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_state_lists_every_member(trio, client: AsyncClient):
    state = await key_state(client, trio["alice"], trio["room_id"])
    assert state["room_id"] == trio["room_id"]
    assert state["members"] == ["sk_alice", "sk_bob", "sk_carol"]
    assert state["key_epoch"] >= 1


@pytest.mark.asyncio
async def test_key_state_requires_membership(trio, client: AsyncClient):
    outsider = await register_and_login(client, "sk_out", "sk_out@e.com", "password123")
    resp = await client.get(
        f"/rooms/{trio['room_id']}/sender-keys/state", headers=auth(outsider)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_key_state_requires_auth(trio, client: AsyncClient):
    resp = await client.get(f"/rooms/{trio['room_id']}/sender-keys/state")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_key_state_unknown_room_404(client: AsyncClient):
    token = await register_and_login(client, "sk_nr", "sk_nr@e.com", "password123")
    resp = await client.get("/rooms/999999/sender-keys/state", headers=auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distribute_stores_one_bundle_per_member(trio, client: AsyncClient):
    resp = await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob"), bundle("sk_carol")]
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["stored"] == 2
    assert resp.json()["skipped"] == []


@pytest.mark.asyncio
async def test_distribute_skips_non_members(trio, client: AsyncClient):
    await register_and_login(client, "sk_stranger", "sk_stranger@e.com", "password123")
    resp = await distribute(
        client,
        trio["alice"],
        trio["room_id"],
        [bundle("sk_bob"), bundle("sk_stranger")],
    )
    assert resp.status_code == 201
    assert resp.json()["stored"] == 1
    assert resp.json()["skipped"] == ["sk_stranger"]


@pytest.mark.asyncio
async def test_distribute_skips_unknown_username(trio, client: AsyncClient):
    resp = await distribute(
        client, trio["alice"], trio["room_id"], [bundle("nobody_at_all")]
    )
    assert resp.status_code == 201
    assert resp.json()["stored"] == 0
    assert resp.json()["skipped"] == ["nobody_at_all"]


@pytest.mark.asyncio
async def test_distribute_skips_self(trio, client: AsyncClient):
    resp = await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_alice"), bundle("sk_bob")]
    )
    assert resp.json()["stored"] == 1
    assert resp.json()["skipped"] == ["sk_alice"]


@pytest.mark.asyncio
async def test_distribute_requires_membership(trio, client: AsyncClient):
    outsider = await register_and_login(client, "sk_o2", "sk_o2@e.com", "password123")
    resp = await distribute(
        client,
        outsider,
        trio["room_id"],
        [bundle("sk_bob")],
        key_epoch=1,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_distribute_rejects_stale_epoch(trio, client: AsyncClient):
    current = (await key_state(client, trio["alice"], trio["room_id"]))["key_epoch"]
    resp = await distribute(
        client,
        trio["alice"],
        trio["room_id"],
        [bundle("sk_bob")],
        key_epoch=max(current - 1, 0) or 1,
    )
    if current > 1:
        assert resp.status_code == 409
    else:  # pragma: no cover - only if joins stopped bumping the epoch
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_distribute_rejects_invalid_base64(trio, client: AsyncClient):
    resp = await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob", blob="not base64!!")]
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_distribute_rejects_oversized_blob(trio, client: AsyncClient):
    from app.services.sender_key_service import MAX_BUNDLE_BYTES

    huge = base64.b64encode(b"x" * (MAX_BUNDLE_BYTES + 1)).decode()
    resp = await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob", blob=huge)]
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_distribute_requires_at_least_one_bundle(trio, client: AsyncClient):
    resp = await distribute(client, trio["alice"], trio["room_id"], [])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_redistributing_the_same_chain_is_idempotent(trio, client: AsyncClient):
    await distribute(client, trio["alice"], trio["room_id"], [bundle("sk_bob")])
    await distribute(client, trio["alice"], trio["room_id"], [bundle("sk_bob")])

    pending = await client.get("/sender-keys", headers=auth(trio["bob"]))
    assert len(pending.json()) == 1


@pytest.mark.asyncio
async def test_new_chain_supersedes_the_previous_one(trio, client: AsyncClient):
    await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob")], chain_id="chain-old"
    )
    await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob")], chain_id="chain-new"
    )

    pending = (await client.get("/sender-keys", headers=auth(trio["bob"]))).json()
    assert [b["chain_id"] for b in pending] == ["chain-new"]


# ---------------------------------------------------------------------------
# Fetching bundles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_fetches_own_bundle_only(trio, client: AsyncClient):
    await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob"), bundle("sk_carol")]
    )

    bobs = (await client.get("/sender-keys", headers=auth(trio["bob"]))).json()
    assert len(bobs) == 1
    assert bobs[0]["sender_username"] == "sk_alice"
    assert bobs[0]["room_id"] == trio["room_id"]
    assert bobs[0]["encrypted_blob"] == BLOB
    assert bobs[0]["signature"] == SIG


@pytest.mark.asyncio
async def test_fetch_marks_delivered_and_does_not_repeat(trio, client: AsyncClient):
    await distribute(client, trio["alice"], trio["room_id"], [bundle("sk_bob")])

    assert len((await client.get("/sender-keys", headers=auth(trio["bob"]))).json()) == 1
    assert (await client.get("/sender-keys", headers=auth(trio["bob"]))).json() == []
    again = await client.get(
        "/sender-keys?include_delivered=true", headers=auth(trio["bob"])
    )
    assert len(again.json()) == 1


@pytest.mark.asyncio
async def test_fetch_can_be_filtered_by_room(trio, client: AsyncClient):
    other_room = await make_group(client, trio["alice"], "sk-room-2")
    await join(client, trio["bob"], other_room)
    await distribute(client, trio["alice"], trio["room_id"], [bundle("sk_bob")])
    await distribute(client, trio["alice"], other_room, [bundle("sk_bob")])

    only = await client.get(
        f"/sender-keys?room_id={other_room}", headers=auth(trio["bob"])
    )
    assert [b["room_id"] for b in only.json()] == [other_room]


@pytest.mark.asyncio
async def test_fetch_filtered_by_room_requires_membership(trio, client: AsyncClient):
    outsider = await register_and_login(client, "sk_o3", "sk_o3@e.com", "password123")
    resp = await client.get(
        f"/sender-keys?room_id={trio['room_id']}", headers=auth(outsider)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_fetch_requires_auth(client: AsyncClient):
    assert (await client.get("/sender-keys")).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Epoch rotation on membership changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_bumps_the_epoch(client: AsyncClient):
    alice = await register_and_login(client, "ep_alice", "ep_alice@e.com", "password123")
    bob = await register_and_login(client, "ep_bob", "ep_bob@e.com", "password123")
    room_id = await make_group(client, alice, "ep-room")

    before = (await key_state(client, alice, room_id))["key_epoch"]
    await join(client, bob, room_id)
    assert (await key_state(client, alice, room_id))["key_epoch"] > before


@pytest.mark.asyncio
async def test_rejoining_does_not_bump_again(trio, client: AsyncClient):
    before = (await key_state(client, trio["alice"], trio["room_id"]))["key_epoch"]
    await join(client, trio["bob"], trio["room_id"])
    assert (
        await key_state(client, trio["alice"], trio["room_id"])
    )["key_epoch"] == before


@pytest.mark.asyncio
async def test_leaving_bumps_the_epoch(trio, client: AsyncClient):
    before = (await key_state(client, trio["alice"], trio["room_id"]))["key_epoch"]
    resp = await client.post(
        f"/rooms/{trio['room_id']}/leave", headers=auth(trio["carol"])
    )
    assert resp.status_code == 200
    assert (
        await key_state(client, trio["alice"], trio["room_id"])
    )["key_epoch"] > before


@pytest.mark.asyncio
async def test_removing_a_member_bumps_the_epoch(trio, client: AsyncClient):
    before = (await key_state(client, trio["alice"], trio["room_id"]))["key_epoch"]
    resp = await client.delete(
        f"/rooms/{trio['room_id']}/members/sk_carol", headers=auth(trio["alice"])
    )
    assert resp.status_code == 200
    assert (
        await key_state(client, trio["alice"], trio["room_id"])
    )["key_epoch"] > before


@pytest.mark.asyncio
async def test_invite_bumps_the_epoch(client: AsyncClient):
    alice = await register_and_login(client, "iv_alice", "iv_alice@e.com", "password123")
    await register_and_login(client, "iv_bob", "iv_bob@e.com", "password123")
    resp = await client.post(
        "/rooms",
        json={"name": "iv-room", "room_type": "group", "is_private": True},
        headers=auth(alice),
    )
    room_id = resp.json()["id"]

    before = (await key_state(client, alice, room_id))["key_epoch"]
    invited = await client.post(
        f"/rooms/{room_id}/invite/iv_bob", headers=auth(alice)
    )
    assert invited.status_code == 200, invited.text
    assert (await key_state(client, alice, room_id))["key_epoch"] > before


@pytest.mark.asyncio
async def test_personal_chat_has_no_epoch_churn(client: AsyncClient):
    alice = await register_and_login(client, "pc_alice", "pc_alice@e.com", "password123")
    await register_and_login(client, "pc_bob", "pc_bob@e.com", "password123")
    resp = await client.post(
        "/rooms/personal", json={"username": "pc_bob"}, headers=auth(alice)
    )
    assert resp.status_code in (200, 201), resp.text
    room_id = resp.json()["id"]
    # Personal chats keep the pairwise ratchet: the epoch stays at its default.
    assert (await key_state(client, alice, room_id))["key_epoch"] == 1


@pytest.mark.asyncio
async def test_removed_member_loses_undelivered_bundles(trio, client: AsyncClient):
    """A removed member must not pick up key material queued before removal."""
    await distribute(
        client, trio["alice"], trio["room_id"], [bundle("sk_bob"), bundle("sk_carol")]
    )
    removed = await client.delete(
        f"/rooms/{trio['room_id']}/members/sk_carol", headers=auth(trio["alice"])
    )
    assert removed.status_code == 200, removed.text

    carols = (await client.get("/sender-keys", headers=auth(trio["carol"]))).json()
    assert carols == []
    # Bob is still a member, so his (pre-rotation) bundle survives: it protects
    # messages that were legitimately sent before the membership change.
    bobs = (await client.get("/sender-keys", headers=auth(trio["bob"]))).json()
    assert len(bobs) == 1


# ---------------------------------------------------------------------------
# Group message send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_group_message_201(trio, client: AsyncClient):
    resp = await send_group(client, trio["alice"], trio["room_id"])
    assert resp.status_code == 201, resp.text
    assert "id" in resp.json() or "message_id" in resp.json()


@pytest.mark.asyncio
async def test_group_message_is_stored_encrypted(
    trio, client: AsyncClient, test_db: AsyncSession
):
    from app.models.message import Message

    await send_group(client, trio["alice"], trio["room_id"])

    msg = (
        await test_db.execute(select(Message).where(Message.room_id == trio["room_id"]))
    ).scalars().first()
    assert msg is not None
    assert msg.is_encrypted is True
    assert msg.body in (None, "")
    assert msg.encrypted_blob == base64.b64decode(BLOB)
    # v3 needs no per-recipient copies at all.
    assert msg.sender_encrypted_blob is None
    assert msg.recipient_id is None


@pytest.mark.asyncio
async def test_group_message_is_visible_to_every_member(trio, client: AsyncClient):
    await send_group(client, trio["alice"], trio["room_id"])

    for who in ("alice", "bob", "carol"):
        history = await client.get(
            f"/rooms/{trio['room_id']}/messages", headers=auth(trio[who])
        )
        assert history.status_code == 200
        assert len(history.json()) == 1


@pytest.mark.asyncio
async def test_send_group_message_requires_membership(trio, client: AsyncClient):
    outsider = await register_and_login(client, "sk_o4", "sk_o4@e.com", "password123")
    resp = await send_group(client, outsider, trio["room_id"], key_epoch=1)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_send_group_message_rejects_stale_epoch(trio, client: AsyncClient):
    current = (await key_state(client, trio["alice"], trio["room_id"]))["key_epoch"]
    assert current > 1, "joins should have bumped the epoch"
    resp = await send_group(client, trio["alice"], trio["room_id"], key_epoch=current - 1)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_send_group_message_rejects_invalid_base64(trio, client: AsyncClient):
    resp = await send_group(client, trio["alice"], trio["room_id"], blob="!!!not b64")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_send_group_message_rejects_oversized_blob(trio, client: AsyncClient):
    from app.routers.sender_keys import MAX_GROUP_BLOB_BYTES

    huge = base64.b64encode(b"x" * (MAX_GROUP_BLOB_BYTES + 1)).decode()
    resp = await send_group(client, trio["alice"], trio["room_id"], blob=huge)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_send_group_message_rejects_empty_blob(trio, client: AsyncClient):
    resp = await send_group(client, trio["alice"], trio["room_id"], blob="")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_send_group_message_unknown_room_404(client: AsyncClient):
    token = await register_and_login(client, "sk_nr2", "sk_nr2@e.com", "password123")
    resp = await client.post(
        "/rooms/999999/group-messages",
        json={
            "encrypted_blob": BLOB,
            "signature": SIG,
            "chain_id": "c",
            "key_epoch": 1,
        },
        headers=auth(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_read_only_room_blocks_non_owner(trio, client: AsyncClient):
    resp = await client.patch(
        f"/rooms/{trio['room_id']}/permissions",
        json={"read_only": True},
        headers=auth(trio["alice"]),
    )
    assert resp.status_code == 200, resp.text

    blocked = await send_group(client, trio["bob"], trio["room_id"])
    assert blocked.status_code == 403
    allowed = await send_group(client, trio["alice"], trio["room_id"])
    assert allowed.status_code == 201
