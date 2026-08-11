"""
Tests for group E2EE (sender keys, blob version 3).

Covers the pure state machine (chain ratcheting, out-of-order delivery, replay,
skip bounds, AAD binding, signature-before-state), rotation policy (every 100
messages and on every epoch bump), encrypted-at-rest persistence, and the
orchestration layer (distribution, ingestion, rotation on membership change,
removed members losing access).

Run with: python -m pytest tests/client/test_sender_key.py -q
"""

import base64
import json

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from crypto.double_ratchet import KeyConsumedError, TooFarAheadError
from crypto.key_cache import PublicKeyCache
from crypto.key_generator import KeyGenerator
from crypto.sender_key import (
    MAX_SKIP,
    ROTATION_MESSAGE_LIMIT,
    SENDER_KEY_VERSION,
    SenderKeyState,
    UnknownSenderKeyError,
    build_distribution_payload,
    decrypt_with_sender_key,
    encrypt_with_sender_key,
    new_sender_key,
    parse_distribution_payload,
    peek_group_header,
    rotation_needed,
)
from crypto.sender_key_store import SenderKeyStore


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _MemStorage:
    """Minimal in-memory stand-in for LocalStorage (get/set key-value)."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _identity():
    return Ed25519PrivateKey.generate()


def _chain(room_id=7, sender="alice", key_epoch=1):
    return new_sender_key(room_id, sender=sender, key_epoch=key_epoch)


def _decode_blob(blob_b64: str) -> dict:
    return json.loads(base64.b64decode(blob_b64).decode())


def _reencode(blob: dict) -> str:
    return base64.b64encode(
        json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_roundtrip_single_message():
    ed = _identity()
    out = _chain()
    inbound = out.copy()

    msg = encrypt_with_sender_key("hello group", out, ed, sender="alice")
    assert decrypt_with_sender_key(msg, inbound, ed.public_key()) == "hello group"


def test_chain_advances_and_keys_differ():
    ed = _identity()
    out = _chain()
    first = encrypt_with_sender_key("one", out, ed)
    second = encrypt_with_sender_key("two", out, ed)

    assert first["iteration"] == 0
    assert second["iteration"] == 1
    assert out.iteration == 2
    # Same chain, but distinct ciphertexts (distinct message keys + nonces).
    assert _decode_blob(first["blob"])["ct"] != _decode_blob(second["blob"])["ct"]


def test_many_messages_in_order():
    ed = _identity()
    out = _chain()
    inbound = out.copy()
    for i in range(50):
        msg = encrypt_with_sender_key(f"m{i}", out, ed)
        assert decrypt_with_sender_key(msg, inbound, ed.public_key()) == f"m{i}"


def test_out_of_order_delivery_uses_skipped_keys():
    ed = _identity()
    out = _chain()
    inbound = out.copy()

    msgs = [encrypt_with_sender_key(f"m{i}", out, ed) for i in range(5)]
    # Deliver the last one first, then the rest backwards.
    assert decrypt_with_sender_key(msgs[4], inbound, ed.public_key()) == "m4"
    for i in (0, 1, 2, 3):
        assert decrypt_with_sender_key(msgs[i], inbound, ed.public_key()) == f"m{i}"


def test_replay_is_rejected():
    ed = _identity()
    out = _chain()
    inbound = out.copy()
    msg = encrypt_with_sender_key("once", out, ed)

    assert decrypt_with_sender_key(msg, inbound, ed.public_key()) == "once"
    with pytest.raises(KeyConsumedError):
        decrypt_with_sender_key(msg, inbound, ed.public_key())


def test_gap_beyond_max_skip_is_refused():
    ed = _identity()
    out = _chain()
    inbound = out.copy()

    for _ in range(MAX_SKIP + 2):
        msg = encrypt_with_sender_key("x", out, ed)
    with pytest.raises(TooFarAheadError):
        decrypt_with_sender_key(msg, inbound, ed.public_key())


def test_signature_is_verified_before_state_changes():
    ed = _identity()
    attacker = _identity()
    out = _chain()
    inbound = out.copy()

    msg = encrypt_with_sender_key("m0", out, ed)
    forged = dict(msg)
    forged["signature"] = base64.b64encode(
        attacker.sign(base64.b64decode(msg["blob"]))
    ).decode()

    with pytest.raises(InvalidSignature):
        decrypt_with_sender_key(forged, inbound, ed.public_key())
    # Chain untouched — the genuine message still decrypts.
    assert inbound.iteration == 0
    assert decrypt_with_sender_key(msg, inbound, ed.public_key()) == "m0"


def test_tampered_ciphertext_fails_aead():
    ed = _identity()
    out = _chain()
    inbound = out.copy()

    msg = encrypt_with_sender_key("secret", out, ed)
    blob = _decode_blob(msg["blob"])
    raw = bytearray(base64.b64decode(blob["ct"]))
    raw[0] ^= 0xFF
    blob["ct"] = base64.b64encode(bytes(raw)).decode()
    tampered_blob = _reencode(blob)
    tampered = {
        "blob": tampered_blob,
        # Re-sign so we get past the signature check and reach the AEAD.
        "signature": base64.b64encode(
            ed.sign(base64.b64decode(tampered_blob))
        ).decode(),
    }
    with pytest.raises(InvalidTag):
        decrypt_with_sender_key(tampered, inbound, ed.public_key())


def test_header_is_bound_as_aad():
    """Rewriting the header (here: the room id) must break decryption."""
    ed = _identity()
    out = _chain(room_id=7)
    inbound = out.copy()
    inbound.room_id = 9

    msg = encrypt_with_sender_key("m", out, ed)
    blob = _decode_blob(msg["blob"])
    blob["room"] = 9
    moved_blob = _reencode(blob)
    moved = {
        "blob": moved_blob,
        "signature": base64.b64encode(ed.sign(base64.b64decode(moved_blob))).decode(),
    }
    with pytest.raises(InvalidTag):
        decrypt_with_sender_key(moved, inbound, ed.public_key())


def test_wrong_chain_is_reported_as_unknown_sender_key():
    ed = _identity()
    out = _chain()
    other = _chain()
    msg = encrypt_with_sender_key("m", out, ed)
    with pytest.raises(UnknownSenderKeyError):
        decrypt_with_sender_key(msg, other, ed.public_key())


def test_peek_group_header():
    ed = _identity()
    out = _chain(room_id=42, sender="bob")
    msg = encrypt_with_sender_key("m", out, ed)
    header = peek_group_header(msg["blob"])
    assert header == {
        "room_id": 42,
        "chain_id": out.chain_id,
        "iteration": 0,
        "sender": "bob",
    }
    assert _decode_blob(msg["blob"])["v"] == SENDER_KEY_VERSION


def test_peek_group_header_returns_none_for_non_v3():
    assert peek_group_header("not base64 at all !!") is None
    assert peek_group_header(base64.b64encode(b'{"v":2}').decode()) is None


# ---------------------------------------------------------------------------
# Rotation policy
# ---------------------------------------------------------------------------


def test_rotation_needed_without_chain():
    assert rotation_needed(None, 1) is True


def test_rotation_needed_after_exactly_100_messages():
    ed = _identity()
    out = _chain()
    for i in range(ROTATION_MESSAGE_LIMIT - 1):
        encrypt_with_sender_key(f"m{i}", out, ed)
        assert rotation_needed(out, 1) is False, f"rotated early at {i}"
    encrypt_with_sender_key("last", out, ed)
    assert out.iteration == ROTATION_MESSAGE_LIMIT
    assert rotation_needed(out, 1) is True


def test_rotation_needed_on_epoch_change():
    out = _chain(key_epoch=3)
    assert rotation_needed(out, 3) is False
    assert rotation_needed(out, 4) is True


# ---------------------------------------------------------------------------
# Distribution payload
# ---------------------------------------------------------------------------


def test_distribution_payload_roundtrip():
    out = _chain(room_id=5, sender="alice", key_epoch=2)
    encrypt_with_sender_key("m0", out, _identity())

    parsed = parse_distribution_payload(build_distribution_payload(out), sender="alice")
    assert parsed.room_id == 5
    assert parsed.chain_id == out.chain_id
    assert parsed.chain_key == out.chain_key
    assert parsed.iteration == out.iteration
    assert parsed.key_epoch == 2
    assert parsed.sender == "alice"


def test_distribution_payload_rejects_foreign_payload():
    with pytest.raises(ValueError):
        parse_distribution_payload(json.dumps({"t": "something-else"}))


def test_distributed_mid_chain_reader_can_follow():
    """A member joining mid-chain gets the chain at its current iteration."""
    ed = _identity()
    out = _chain()
    for i in range(10):
        encrypt_with_sender_key(f"old{i}", out, ed)

    late = parse_distribution_payload(build_distribution_payload(out), sender="alice")
    msg = encrypt_with_sender_key("new", out, ed)
    assert decrypt_with_sender_key(msg, late, ed.public_key()) == "new"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _store(storage=None, account="alice"):
    x = X25519PrivateKey.generate()
    return SenderKeyStore(
        storage if storage is not None else _MemStorage(),
        x.private_bytes_raw(),
        account,
    ), x


def test_store_persists_own_chain_across_restart():
    storage = _MemStorage()
    store, x = _store(storage)
    chain = _chain()
    store.put_own(chain)

    reloaded = SenderKeyStore(storage, x.private_bytes_raw(), "alice")
    got = reloaded.get_own(chain.room_id)
    assert got is not None
    assert got.chain_id == chain.chain_id
    assert got.chain_key == chain.chain_key


def test_store_is_encrypted_at_rest():
    storage = _MemStorage()
    store, _ = _store(storage)
    chain = _chain()
    store.put_own(chain)

    raw = storage.get("sender_keys.alice")
    assert isinstance(raw, str)
    assert chain.chain_id not in raw
    assert base64.b64encode(chain.chain_key).decode() not in raw


def test_store_wrong_account_key_reads_nothing():
    storage = _MemStorage()
    store, _ = _store(storage)
    store.put_own(_chain())

    other_x = X25519PrivateKey.generate()
    other = SenderKeyStore(storage, other_x.private_bytes_raw(), "alice")
    assert other.get_own(7) is None


def test_store_keeps_previous_chain_after_rotation():
    """A rotation must not orphan messages sent on the old chain."""
    store, _ = _store()
    old = _chain(room_id=1, sender="bob")
    new = _chain(room_id=1, sender="bob")
    store.put_inbound(1, "bob", old)
    store.put_inbound(1, "bob", new)

    assert store.get_inbound(1, "bob", old.chain_id).chain_id == old.chain_id
    assert store.get_inbound(1, "bob", new.chain_id).chain_id == new.chain_id
    # Without an explicit chain id the newest chain wins.
    assert store.get_inbound(1, "bob").chain_id == new.chain_id


def test_store_evicts_the_oldest_chains():
    from crypto.sender_key_store import _MAX_CHAINS_PER_SENDER

    store, _ = _store()
    chains = [_chain(room_id=1, sender="bob") for _ in range(_MAX_CHAINS_PER_SENDER + 2)]
    for chain in chains:
        store.put_inbound(1, "bob", chain)

    assert store.get_inbound(1, "bob", chains[0].chain_id) is None
    assert store.get_inbound(1, "bob", chains[1].chain_id) is None
    assert store.get_inbound(1, "bob", chains[-1]. chain_id) is not None
    assert store.senders(1) == ["bob"]


def test_store_migrates_pre_rotation_layout():
    """Chains persisted by an older build (keyed without chain id) survive."""
    from crypto.at_rest import seal

    storage = _MemStorage()
    store, x = _store(storage)
    chain = _chain(room_id=1, sender="bob")
    storage.set(
        "sender_keys.alice",
        seal(store._key, {"own": {}, "inbound": {"1\x1fbob": chain.to_dict()}}),
    )

    reloaded = SenderKeyStore(storage, x.private_bytes_raw(), "alice")
    assert reloaded.get_inbound(1, "bob", chain.chain_id).chain_key == chain.chain_key


def test_store_drop_inbound_removes_every_chain_of_a_sender():
    store, _ = _store()
    a, b = _chain(room_id=1, sender="bob"), _chain(room_id=1, sender="bob")
    store.put_inbound(1, "bob", a)
    store.put_inbound(1, "bob", b)

    store.drop_inbound(1, "bob")
    assert store.get_inbound(1, "bob") is None
    assert store.senders(1) == []


def test_store_inbound_chains_are_per_sender():
    store, _ = _store()
    a = _chain(room_id=1, sender="bob")
    b = _chain(room_id=1, sender="carol")
    store.put_inbound(1, "bob", a)
    store.put_inbound(1, "carol", b)

    assert store.get_inbound(1, "bob").chain_id == a.chain_id
    assert store.get_inbound(1, "carol").chain_id == b.chain_id
    assert sorted(store.senders(1)) == ["bob", "carol"]


def test_store_distribution_bookkeeping_gcs_old_chains():
    store, _ = _store()
    store.mark_distributed(1, "chain-a", ["bob", "carol"])
    assert store.distributed_to(1, "chain-a") == {"bob", "carol"}

    store.mark_distributed(1, "chain-b", ["bob"])
    assert store.distributed_to(1, "chain-b") == {"bob"}
    assert store.distributed_to(1, "chain-a") == set()


def test_drop_own_clears_distribution_state():
    store, _ = _store()
    chain = _chain(room_id=3)
    store.put_own(chain)
    store.mark_distributed(3, chain.chain_id, ["bob"])

    store.drop_own(3)
    assert store.get_own(3) is None
    assert store.distributed_to(3, chain.chain_id) == set()


def test_state_serialization_roundtrip_keeps_skipped_keys():
    ed = _identity()
    out = _chain()
    inbound = out.copy()
    msgs = [encrypt_with_sender_key(f"m{i}", out, ed) for i in range(3)]
    decrypt_with_sender_key(msgs[2], inbound, ed.public_key())  # creates skips

    revived = SenderKeyState.from_dict(inbound.to_dict())
    assert decrypt_with_sender_key(msgs[0], revived, ed.public_key()) == "m0"
    assert decrypt_with_sender_key(msgs[1], revived, ed.public_key()) == "m1"


# ---------------------------------------------------------------------------
# Orchestration (group_session) against a fake server
# ---------------------------------------------------------------------------


class _User:
    def __init__(self, uid, username):
        self.id = uid
        self.username = username
        self.display_name = username


class _State:
    """Just enough of AppState for the group session helpers."""

    def __init__(self, user, ed_priv, x_priv):
        self.current_user = user
        self.ed25519_private = ed_priv
        self.x25519_private = x_priv
        self.secure_storage = _MemStorage()
        self.public_key_cache = PublicKeyCache()
        self.ratchet_sessions = None
        self.message_store = None
        self.sender_key_store = None


class _FakeServer:
    """In-memory stand-in for the sender-key HTTP API."""

    def __init__(self):
        self.rooms: dict[int, dict] = {}
        self.pending: dict[str, list[dict]] = {}
        self.users: dict[str, dict] = {}
        self.messages: list[dict] = []

    def add_room(self, room_id, members):
        self.rooms[room_id] = {"key_epoch": 1, "members": list(members)}

    def register(self, username, uid, ed_pub, x_pub):
        self.users[username] = {
            "identity_pub_ed25519": base64.b64encode(
                KeyGenerator.serialize_public_key(ed_pub)
            ).decode(),
            "identity_pub_x25519": base64.b64encode(
                KeyGenerator.serialize_public_key(x_pub)
            ).decode(),
            "user_id": uid,
        }

    def membership_change(self, room_id, members):
        """Mirror the server behaviour: change members, bump the epoch.

        Undelivered bundles are dropped only for users who left, exactly like
        ``sender_key_service.bump_key_epoch``.
        """
        room = self.rooms[room_id]
        room["members"] = list(members)
        room["key_epoch"] += 1
        for recipient, queue in self.pending.items():
            queue[:] = [
                b
                for b in queue
                if b["room_id"] != room_id
                or (recipient in members and b["sender_username"] in members)
            ]


class _FakeClient:
    """APIClient surface used by crypto.group_session."""

    def __init__(self, server: _FakeServer, me: str):
        self.server = server
        self.me = me

    async def get_public_keys(self, username):
        return self.server.users[username]

    async def get_sender_key_state(self, room_id):
        room = self.server.rooms[room_id]
        return {
            "room_id": room_id,
            "key_epoch": room["key_epoch"],
            "members": list(room["members"]),
        }

    async def distribute_sender_keys(self, room_id, chain_id, key_epoch, bundles):
        room = self.server.rooms[room_id]
        skipped = []
        stored = 0
        for bundle in bundles:
            recipient = bundle["recipient_username"]
            if recipient not in room["members"] or recipient == self.me:
                skipped.append(recipient)
                continue
            self.server.pending.setdefault(recipient, []).append(
                {
                    "room_id": room_id,
                    "sender_username": self.me,
                    "chain_id": chain_id,
                    "key_epoch": key_epoch,
                    "encrypted_blob": bundle["encrypted_blob"],
                    "signature": bundle["signature"],
                }
            )
            stored += 1
        return {"stored": stored, "skipped": skipped, "key_epoch": key_epoch}

    async def get_pending_sender_keys(self, room_id=None):
        queue = self.server.pending.get(self.me, [])
        taken = [b for b in queue if room_id is None or b["room_id"] == room_id]
        self.server.pending[self.me] = [b for b in queue if b not in taken]
        return taken

    async def send_group_message(self, room_id, encrypted_blob_b64, signature_b64, **kw):
        self.server.messages.append(
            {
                "room_id": room_id,
                "sender": self.me,
                "blob": encrypted_blob_b64,
                "signature": signature_b64,
            }
        )
        return {"id": len(self.server.messages)}


class _Party:
    def __init__(self, server, uid, username):
        self.username = username
        self.ed = Ed25519PrivateKey.generate()
        self.x = X25519PrivateKey.generate()
        self.state = _State(_User(uid, username), self.ed, self.x)
        self.client = _FakeClient(server, username)
        server.register(username, uid, self.ed.public_key(), self.x.public_key())


@pytest.fixture
def group():
    server = _FakeServer()
    alice = _Party(server, 1, "alice")
    bob = _Party(server, 2, "bob")
    carol = _Party(server, 3, "carol")
    server.add_room(10, ["alice", "bob", "carol"])
    return server, alice, bob, carol


async def _send(party, room_id, text):
    from crypto.group_session import encrypt_group_message

    return await encrypt_group_message(party.state, party.client, room_id, text)


async def _receive(party, msg):
    from crypto.group_session import decrypt_group_message

    return await decrypt_group_message(
        party.state, party.client, msg["blob"], msg["signature"]
    )


@pytest.mark.asyncio
async def test_group_message_reaches_every_member(group):
    _, alice, bob, carol = group
    msg = await _send(alice, 10, "hello everyone")

    assert await _receive(bob, msg) == "hello everyone"
    assert await _receive(carol, msg) == "hello everyone"


@pytest.mark.asyncio
async def test_one_encryption_per_message_regardless_of_room_size(group):
    server, alice, bob, carol = group
    first = await _send(alice, 10, "one")
    second = await _send(alice, 10, "two")

    # Distribution happens once per chain, not once per message.
    assert len(server.pending.get("bob", [])) == 1
    assert peek_group_header(first["blob"])["chain_id"] == peek_group_header(
        second["blob"]
    )["chain_id"]
    assert await _receive(bob, first) == "one"
    assert await _receive(bob, second) == "two"


@pytest.mark.asyncio
async def test_sender_cannot_be_impersonated(group):
    server, alice, bob, carol = group
    msg = await _send(alice, 10, "from alice")
    await _receive(bob, msg)  # bob now holds alice's chain key

    # Bob knows the chain key but cannot sign as alice.
    from crypto.sender_key import encrypt_with_sender_key as enc

    alices_chain = bob.state.sender_key_store.get_inbound(10, "alice")
    forged = enc("i am alice", alices_chain.copy(), bob.ed, sender="alice")
    with pytest.raises(InvalidSignature):
        await _receive(carol, forged)


@pytest.mark.asyncio
async def test_rotation_after_100_messages_is_redistributed(group):
    server, alice, bob, _ = group
    first = await _send(alice, 10, "m0")
    for i in range(1, ROTATION_MESSAGE_LIMIT):
        await _send(alice, 10, f"m{i}")
    after = await _send(alice, 10, "post-rotation")

    assert peek_group_header(first["blob"])["chain_id"] != (
        peek_group_header(after["blob"])["chain_id"]
    )
    assert peek_group_header(after["blob"])["iteration"] == 0
    # Bob can follow across the rotation boundary.
    assert await _receive(bob, first) == "m0"
    assert await _receive(bob, after) == "post-rotation"


@pytest.mark.asyncio
async def test_messages_from_before_a_rotation_stay_readable(group):
    """A member who reads late must not lose the tail of the previous chain."""
    server, alice, bob, _ = group
    before = await _send(alice, 10, "sent just before the rotation")
    server.membership_change(10, ["alice", "bob", "carol"])
    after = await _send(alice, 10, "sent on the new chain")

    # Bob reads both only now, newest first.
    assert await _receive(bob, after) == "sent on the new chain"
    assert await _receive(bob, before) == "sent just before the rotation"


@pytest.mark.asyncio
async def test_new_member_cannot_read_history_but_reads_new_messages(group):
    server, alice, bob, carol = group
    old = await _send(alice, 10, "before dave joined")

    dave = _Party(server, 4, "dave")
    server.membership_change(10, ["alice", "bob", "carol", "dave"])

    fresh = await _send(alice, 10, "after dave joined")
    assert await _receive(dave, fresh) == "after dave joined"
    with pytest.raises(UnknownSenderKeyError):
        await _receive(dave, old)


@pytest.mark.asyncio
async def test_removed_member_cannot_read_later_messages(group):
    server, alice, bob, carol = group
    before = await _send(alice, 10, "carol is here")
    assert await _receive(carol, before) == "carol is here"

    server.membership_change(10, ["alice", "bob"])
    after = await _send(alice, 10, "carol is gone")

    assert await _receive(bob, after) == "carol is gone"
    with pytest.raises(UnknownSenderKeyError):
        await _receive(carol, after)


@pytest.mark.asyncio
async def test_epoch_bump_forces_new_chain(group):
    server, alice, bob, _ = group
    first = await _send(alice, 10, "epoch 1")
    server.membership_change(10, ["alice", "bob"])
    second = await _send(alice, 10, "epoch 2")

    assert peek_group_header(first["blob"])["chain_id"] != (
        peek_group_header(second["blob"])["chain_id"]
    )
    assert second["key_epoch"] == 2


@pytest.mark.asyncio
async def test_offline_member_catches_up_via_sync(group):
    server, alice, bob, _ = group
    msgs = [await _send(alice, 10, f"m{i}") for i in range(3)]

    # Bob was offline: he never received the WS push, only the stored bundle.
    from crypto.group_session import sync_sender_keys

    assert await sync_sender_keys(bob.state, bob.client, room_id=10) == 1
    for i, msg in enumerate(msgs):
        assert await _receive(bob, msg) == f"m{i}"


@pytest.mark.asyncio
async def test_unknown_sender_key_when_bundle_never_arrives(group):
    server, alice, bob, _ = group
    msg = await _send(alice, 10, "hi")
    server.pending["bob"] = []  # bundle lost

    with pytest.raises(UnknownSenderKeyError):
        await _receive(bob, msg)


@pytest.mark.asyncio
async def test_failed_decrypt_does_not_advance_the_chain(group):
    server, alice, bob, _ = group
    first = await _send(alice, 10, "m0")
    second = await _send(alice, 10, "m1")

    corrupt = dict(second)
    blob = _decode_blob(second["blob"])
    raw = bytearray(base64.b64decode(blob["ct"]))
    raw[0] ^= 0xFF
    blob["ct"] = base64.b64encode(bytes(raw)).decode()
    corrupt["blob"] = _reencode(blob)
    corrupt["signature"] = base64.b64encode(
        alice.ed.sign(base64.b64decode(corrupt["blob"]))
    ).decode()

    assert await _receive(bob, first) == "m0"
    with pytest.raises(InvalidTag):
        await _receive(bob, corrupt)
    # The genuine second message is still readable.
    assert await _receive(bob, second) == "m1"


@pytest.mark.asyncio
async def test_every_member_can_send_concurrently(group):
    server, alice, bob, carol = group
    from_alice = await _send(alice, 10, "from alice")
    from_bob = await _send(bob, 10, "from bob")

    assert await _receive(bob, from_alice) == "from alice"
    assert await _receive(alice, from_bob) == "from bob"
    assert await _receive(carol, from_alice) == "from alice"
    assert await _receive(carol, from_bob) == "from bob"


@pytest.mark.asyncio
async def test_chain_survives_client_restart(group):
    server, alice, bob, _ = group
    first = await _send(alice, 10, "before restart")

    # Simulate a restart: same storage, fresh store instances.
    alice.state.sender_key_store = None
    second = await _send(alice, 10, "after restart")

    assert peek_group_header(first["blob"])["chain_id"] == (
        peek_group_header(second["blob"])["chain_id"]
    )
    assert peek_group_header(second["blob"])["iteration"] == 1
    assert await _receive(bob, first) == "before restart"
    assert await _receive(bob, second) == "after restart"


@pytest.mark.asyncio
async def test_file_key_is_sealed_for_the_room(group):
    server, alice, bob, _ = group
    from crypto.group_session import open_file_key, seal_file_key_for_room

    file_key = base64.b64encode(b"\x07" * 32).decode()
    sealed = await seal_file_key_for_room(alice.state, alice.client, 10, file_key)

    got = await open_file_key(
        bob.state, bob.client, 99, sealed["key_blob"], sealed["key_signature"]
    )
    assert got == file_key
    # Second download reuses the cached key even though the message key is gone.
    again = await open_file_key(
        bob.state, bob.client, 99, sealed["key_blob"], sealed["key_signature"]
    )
    assert again == file_key
