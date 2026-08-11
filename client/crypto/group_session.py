"""
Group session orchestration for sender-key (v3) encryption.

This is the glue between the pure state machine in ``crypto.sender_key``, the
encrypted persistence in ``crypto.sender_key_store`` and the server API. It
owns three flows:

**Distribution.** Before we can send in a group room we need an outbound chain
and every member needs a copy of it. The chain key is shipped inside a normal
*pairwise Double Ratchet* message (one per member, uploaded in a single
request), so the server routes key material it cannot read.

**Rotation.** A chain is replaced when it has encrypted
``ROTATION_MESSAGE_LIMIT`` (100) messages, or when the server reports a new
``key_epoch`` — which it bumps on every join, invite, leave and removal. The
new chain is distributed only to the *current* member list, which is what makes
a removed member unable to read anything sent after their removal.

**Reception.** An incoming v3 blob names its room, sender and chain. If we have
never seen that chain (offline while it was distributed, or it was just
rotated) we pull our pending bundles from the server and try again.
"""

from __future__ import annotations

import logging
from base64 import b64decode
from typing import TYPE_CHECKING, Any

from crypto.key_generator import KeyGenerator
from crypto.message_store import get_message_store
from crypto.ratchet_facade import RatchetDecryptor, RatchetEncryptor
from crypto.ratchet_session_store import get_session_store
from crypto.sender_key import (
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
from crypto.sender_key_store import get_sender_key_store

if TYPE_CHECKING:  # pragma: no cover - typing only
    from state import AppState

logger = logging.getLogger(__name__)

__all__ = [
    "GROUP_ROOM_TYPES",
    "ROTATION_MESSAGE_LIMIT",
    "SENDER_KEY_VERSION",
    "UnknownSenderKeyError",
    "decrypt_group_message",
    "encrypt_group_message",
    "ingest_bundle",
    "is_group_room",
    "open_file_key",
    "peek_group_header",
    "seal_file_key_for_room",
    "sync_sender_keys",
]

#: Room types that use sender keys. Personal chats keep the pairwise ratchet,
#: which is strictly stronger for two parties.
GROUP_ROOM_TYPES = ("group", "public")


def is_group_room(room: Any) -> bool:
    return str(getattr(room, "room_type", "")) in GROUP_ROOM_TYPES


def _bare(handle: str) -> str:
    """Local part of a ``user@server`` handle."""
    return handle.split("@", 1)[0]


def _is_me(state: "AppState", handle: str) -> bool:
    me = state.current_user.username if state.current_user else None
    return me is not None and _bare(handle) == _bare(me)


async def _peer_keys(state: "AppState", client: Any, username: str) -> dict:
    """Public keys of *username*, from the cache or the server."""
    cache = state.public_key_cache
    keys = cache.get_public_keys(username) if cache else None
    if keys:
        return keys

    data = await client.get_public_keys(username)
    ed25519_pub = KeyGenerator.load_ed25519_public_key(
        b64decode(data["identity_pub_ed25519"])
    )
    x25519_pub = KeyGenerator.load_x25519_public_key(
        b64decode(data["identity_pub_x25519"])
    )
    if cache:
        cache.set_public_keys(
            username, ed25519_pub, x25519_pub, str(data.get("user_id", ""))
        )
    return {
        "ed25519_pub": ed25519_pub,
        "x25519_pub": x25519_pub,
        "user_id": data.get("user_id", ""),
    }


# ---------------------------------------------------------------------------
# Outbound: chain creation, distribution, rotation
# ---------------------------------------------------------------------------


async def _distribute(
    state: "AppState",
    client: Any,
    chain: SenderKeyState,
    recipients: list[str],
) -> list[str]:
    """Ship *chain* to every handle in *recipients* over the pairwise ratchet.

    Returns the handles the server accepted. Failures are non-fatal: the member
    simply stays without the chain and will be served on the next send, so one
    unreachable member never blocks the room.
    """
    if not recipients:
        return []

    payload = build_distribution_payload(chain)
    encryptor = RatchetEncryptor()
    session_store = get_session_store(state)
    bundles: list[dict] = []

    for handle in recipients:
        try:
            keys = await _peer_keys(state, client, handle)
            sealed = encryptor.encrypt_message(
                plaintext=payload,
                peer_key=handle,
                peer_identity_x25519_pub=keys["x25519_pub"],
                sender_ed25519_priv=state.ed25519_private,
                sender_x25519_priv=state.x25519_private,
                sender_id=str(state.current_user.id) if state.current_user else "",
                recipient_id=str(keys.get("user_id", "")),
                store=session_store,
            )
        except Exception as exc:  # noqa: BLE001 - skip just this member
            logger.warning("[GroupSession] cannot seal chain for %s: %s", handle, exc)
            continue
        bundles.append(
            {
                "recipient_username": handle,
                # Only the recipient copy travels: our own chain already lives
                # in the local sender-key store.
                "encrypted_blob": sealed["blob"],
                "signature": sealed["signature"],
            }
        )

    if not bundles:
        return []

    result = await client.distribute_sender_keys(
        room_id=chain.room_id,
        chain_id=chain.chain_id,
        key_epoch=chain.key_epoch,
        bundles=bundles,
    )
    skipped = set(result.get("skipped") or [])
    return [b["recipient_username"] for b in bundles if b["recipient_username"] not in skipped]


async def ensure_group_session(
    state: "AppState", client: Any, room_id: int
) -> SenderKeyState:
    """Return a usable outbound chain for *room_id*, rotating/distributing it.

    Rotation happens on epoch change (membership churn) and every
    ``ROTATION_MESSAGE_LIMIT`` messages. After rotation the fresh chain is sent
    to every current member; on an unchanged chain only members that have not
    received it yet are served, so a steady-state send costs nothing extra.
    """
    store = get_sender_key_store(state)
    if store is None:
        raise RuntimeError("sender-key store unavailable (identity keys missing)")

    key_state = await client.get_sender_key_state(room_id)
    key_epoch = int(key_state.get("key_epoch", 1))
    members = [
        m for m in (key_state.get("members") or []) if not _is_me(state, m)
    ]

    chain = store.get_own(room_id)
    if rotation_needed(chain, key_epoch):
        reason = (
            "no chain"
            if chain is None
            else (
                f"epoch {chain.key_epoch} -> {key_epoch}"
                if chain.key_epoch != key_epoch
                else f"{chain.iteration} messages sent"
            )
        )
        logger.info("[GroupSession] rotating sender key for room %s (%s)", room_id, reason)
        chain = new_sender_key(
            room_id,
            sender=state.current_user.username if state.current_user else "",
            key_epoch=key_epoch,
        )
        store.put_own(chain)
        pending = members
    else:
        pending = [m for m in members if m not in store.distributed_to(room_id, chain.chain_id)]

    if pending:
        served = await _distribute(state, client, chain, pending)
        if served:
            store.mark_distributed(room_id, chain.chain_id, served)

    return chain


async def encrypt_group_message(
    state: "AppState", client: Any, room_id: int, plaintext: str
) -> dict:
    """Encrypt *plaintext* for a whole room. Returns the v3 wire fields."""
    chain = await ensure_group_session(state, client, room_id)
    store = get_sender_key_store(state)

    encrypted = encrypt_with_sender_key(
        plaintext,
        chain,
        state.ed25519_private,
        sender=state.current_user.username if state.current_user else "",
    )
    # The chain advanced — persist immediately so a crash can never reuse a
    # message key (catastrophic for AES-GCM).
    if store is not None:
        store.put_own(chain)
    return encrypted


# ---------------------------------------------------------------------------
# Inbound: bundle ingestion and decryption
# ---------------------------------------------------------------------------


async def ingest_bundle(state: "AppState", client: Any, bundle: dict) -> bool:
    """Decrypt one distribution bundle and remember the sender's chain."""
    store = get_sender_key_store(state)
    if store is None:
        return False

    sender = bundle.get("sender_username") or ""
    room_id = int(bundle.get("room_id", 0))
    if not sender or _is_me(state, sender):
        return False

    try:
        keys = await _peer_keys(state, client, sender)
        payload = RatchetDecryptor().decrypt_message(
            {"blob": bundle["encrypted_blob"], "signature": bundle["signature"]},
            peer_key=sender,
            recipient_x25519_priv=state.x25519_private,
            sender_ed25519_pub=keys["ed25519_pub"],
            sender_x25519_pub=keys["x25519_pub"],
            store=get_session_store(state),
        )
        chain = parse_distribution_payload(payload, sender=sender)
    except Exception as exc:  # noqa: BLE001 - one bad bundle must not break sync
        logger.warning("[GroupSession] bad sender-key bundle from %s: %s", sender, exc)
        return False

    if chain.room_id != room_id:
        logger.warning("[GroupSession] bundle room mismatch from %s", sender)
        return False

    existing = store.get_inbound(room_id, sender, chain.chain_id)
    if existing is not None:
        # Already known: keep our copy, it may have ratcheted forward already.
        return True

    store.put_inbound(room_id, sender, chain)
    logger.info(
        "[GroupSession] installed chain %s from %s in room %s",
        chain.chain_id[:8],
        sender,
        room_id,
    )
    return True


async def sync_sender_keys(
    state: "AppState", client: Any, room_id: int | None = None
) -> int:
    """Fetch and install every sender-key bundle addressed to us."""
    store = get_sender_key_store(state)
    if store is None:
        return 0
    try:
        bundles = await client.get_pending_sender_keys(room_id=room_id)
    except Exception as exc:  # noqa: BLE001 - offline is not an error here
        logger.warning("[GroupSession] cannot fetch sender keys: %s", exc)
        return 0

    installed = 0
    for bundle in bundles:
        if await ingest_bundle(state, client, bundle):
            installed += 1
    return installed


async def decrypt_group_message(
    state: "AppState", client: Any, encrypted_blob: str, signature: str
) -> str:
    """Verify and decrypt a v3 group ciphertext.

    Raises ``UnknownSenderKeyError`` when the sender's chain is still unknown
    after a re-sync (e.g. the sender has not distributed it to us yet).
    """
    header = peek_group_header(encrypted_blob)
    if header is None:
        raise ValueError("not a sender-key (v3) blob")

    store = get_sender_key_store(state)
    if store is None:
        raise UnknownSenderKeyError("sender-key store unavailable")

    room_id = header["room_id"]
    sender = header["sender"]
    if not sender:
        raise UnknownSenderKeyError("v3 blob without a sender handle")

    keys = await _peer_keys(state, client, sender)
    chain_id = header["chain_id"]
    chain = store.get_inbound(room_id, sender, chain_id)

    if chain is None:
        # The chain was rotated (or we were offline when it was shipped):
        # pull whatever the server holds for us and look again.
        await sync_sender_keys(state, client, room_id=room_id)
        chain = store.get_inbound(room_id, sender, chain_id)
    if chain is None:
        raise UnknownSenderKeyError(
            f"no sender key for {sender} chain {chain_id[:8]} in room {room_id}"
        )

    # Decrypt on a copy: the chain must only advance if the AEAD check passes,
    # otherwise a corrupt frame would burn keys of legitimate messages.
    working = chain.copy()
    plaintext = decrypt_with_sender_key(
        {"blob": encrypted_blob, "signature": signature},
        working,
        keys["ed25519_pub"],
    )
    store.put_inbound(room_id, sender, working)
    return plaintext


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
#
# File *bodies* are already recipient-independent (random per-file AES-256-GCM
# key, chunked).  Only the file key needs to reach the room, and the cheapest
# safe way to do that is to send it as a normal sender-key message: one wrap for
# the whole room, authenticated by the same Ed25519 signature, rotated by the
# same epoch rules.  The sealed key rides in the existing ``key_blob`` /
# ``key_signature`` columns, so the server schema is untouched.


def _file_key_cache_key(file_id: Any) -> str:
    return f"file-key:{file_id}"


async def seal_file_key_for_room(
    state: "AppState", client: Any, room_id: int, file_key_b64: str
) -> dict:
    """Seal a file key for every member of *room_id*.

    Returns ``{"key_blob", "key_signature"}`` ready for the upload headers.
    """
    sealed = await encrypt_group_message(state, client, room_id, file_key_b64)
    return {"key_blob": sealed["blob"], "key_signature": sealed["signature"]}


async def open_file_key(
    state: "AppState",
    client: Any,
    file_id: Any,
    key_blob: str,
    signature: str,
) -> str:
    """Recover a room-sealed file key, caching it for repeated downloads.

    The sender-key message key that protects the blob is burned on first use,
    so the recovered key is cached (encrypted at rest, next to decrypted
    message bodies) — otherwise a second download of the same attachment would
    fail with ``KeyConsumedError``.
    """
    cache = get_message_store(state)
    if cache is not None and file_id is not None:
        cached = cache.get(_file_key_cache_key(file_id))
        if cached:
            return cached

    file_key_b64 = await decrypt_group_message(state, client, key_blob, signature)

    if cache is not None and file_id is not None:
        cache.put(_file_key_cache_key(file_id), file_key_b64)
    return file_key_b64
