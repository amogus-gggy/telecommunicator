"""
Persistence for group sender-key material.

Three kinds of state are kept per account, all encrypted at rest under the
account identity key (see ``crypto.at_rest``):

``own``
    The outbound chain we use to encrypt our own messages in a room, keyed by
    ``room_id``. Also remembers which members already received the current
    chain so a rotation only costs one pairwise message per member.

``inbound``
    One chain per ``(room_id, sender, chain_id)`` triple, built from a
    distribution bundle received over the pairwise Double Ratchet. A handful of
    superseded chains per sender are retained on purpose: a rotation does not
    invalidate messages that were sent just before it, and a client that was
    offline across a rotation must still be able to read both sides of it.

``pending``
    Ciphertexts that arrived before their distribution bundle did, so they can
    be decrypted retroactively once the bundle shows up.

Everything is written through on mutation so a restarted client keeps talking
on the same chain instead of forcing a (costly) rotation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from crypto.at_rest import derive_storage_key, open_value, seal
from crypto.sender_key import SenderKeyState

if TYPE_CHECKING:
    from state import AppState

logger = logging.getLogger(__name__)

_PURPOSE = "sender-keys"

#: Bound on the retained "arrived too early" ciphertexts.
_MAX_PENDING = 200

#: How many chains to keep per (room, sender) before evicting the oldest.
#: Covers being offline across a few rotations without unbounded growth.
_MAX_CHAINS_PER_SENDER = 5

_SEP = "\x1f"


def _inbound_key(room_id: int, sender: str, chain_id: str) -> str:
    return f"{int(room_id)}{_SEP}{sender}{_SEP}{chain_id}"


def _inbound_prefix(room_id: int, sender: str) -> str:
    return f"{int(room_id)}{_SEP}{sender}{_SEP}"


class SenderKeyStore:
    """Loads/persists the sender-key state of one account."""

    def __init__(self, storage: Any, identity_x25519_priv_raw: bytes, account: str):
        self._storage = storage
        self._account = account
        self._store_key = f"sender_keys.{account}"
        self._key = derive_storage_key(identity_x25519_priv_raw, account, _PURPOSE)
        self._own: dict[str, SenderKeyState] = {}
        self._inbound: dict[str, SenderKeyState] = {}
        #: room_id -> chain_id -> set of member handles already served
        self._distributed: dict[str, dict[str, list[str]]] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        raw = self._storage.get(self._store_key) if self._storage is not None else None
        data = open_value(self._key, raw)
        if not isinstance(data, dict):
            return
        for room_id, state_dict in (data.get("own") or {}).items():
            try:
                self._own[str(room_id)] = SenderKeyState.from_dict(state_dict)
            except Exception as exc:  # noqa: BLE001 - tolerate a corrupt entry
                logger.warning("[SenderKeyStore] dropping own chain %r: %s", room_id, exc)
        for key, state_dict in (data.get("inbound") or {}).items():
            try:
                state = SenderKeyState.from_dict(state_dict)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SenderKeyStore] dropping inbound chain %r: %s", key, exc)
                continue
            parts = str(key).split(_SEP)
            if len(parts) == 2:  # pre-chain_id layout: migrate in place
                key = _inbound_key(state.room_id, parts[1], state.chain_id)
            self._inbound[str(key)] = state
        distributed = data.get("distributed") or {}
        if isinstance(distributed, dict):
            self._distributed = {
                str(room): {str(cid): list(members) for cid, members in chains.items()}
                for room, chains in distributed.items()
                if isinstance(chains, dict)
            }

    def _flush(self) -> None:
        if self._storage is None:
            return
        payload = {
            "own": {rid: st.to_dict() for rid, st in self._own.items()},
            "inbound": {k: st.to_dict() for k, st in self._inbound.items()},
            "distributed": self._distributed,
        }
        self._storage.set(self._store_key, seal(self._key, payload))

    # -- outbound chain ---------------------------------------------------

    def get_own(self, room_id: int) -> SenderKeyState | None:
        return self._own.get(str(int(room_id)))

    def put_own(self, state: SenderKeyState) -> None:
        self._own[str(int(state.room_id))] = state
        self._flush()

    def drop_own(self, room_id: int) -> None:
        if self._own.pop(str(int(room_id)), None) is not None:
            self._distributed.pop(str(int(room_id)), None)
            self._flush()

    # -- distribution bookkeeping ----------------------------------------

    def distributed_to(self, room_id: int, chain_id: str) -> set[str]:
        return set(self._distributed.get(str(int(room_id)), {}).get(chain_id, []))

    def mark_distributed(self, room_id: int, chain_id: str, members: list[str]) -> None:
        room_key = str(int(room_id))
        # Only the current chain matters; older chains are garbage collected so
        # the bookkeeping cannot grow without bound.
        chains = {chain_id: sorted(set(self._distributed.get(room_key, {}).get(chain_id, [])) | set(members))}
        self._distributed[room_key] = chains
        self._flush()

    # -- inbound chains ---------------------------------------------------

    def get_inbound(
        self, room_id: int, sender: str, chain_id: str | None = None
    ) -> SenderKeyState | None:
        """Return a sender's chain — a specific one, or the most recent."""
        if chain_id is not None:
            return self._inbound.get(_inbound_key(room_id, sender, chain_id))
        keys = self._chain_keys(room_id, sender)
        return self._inbound[keys[-1]] if keys else None

    def put_inbound(self, room_id: int, sender: str, state: SenderKeyState) -> None:
        key = _inbound_key(room_id, sender, state.chain_id)
        # Re-insert last so the newest chain stays at the end of the dict.
        self._inbound.pop(key, None)
        self._inbound[key] = state
        for stale in self._chain_keys(room_id, sender)[:-_MAX_CHAINS_PER_SENDER]:
            self._inbound.pop(stale, None)
        self._flush()

    def drop_inbound(
        self, room_id: int, sender: str, chain_id: str | None = None
    ) -> None:
        """Forget one chain, or every chain of *sender* in *room_id*."""
        keys = (
            [_inbound_key(room_id, sender, chain_id)]
            if chain_id is not None
            else self._chain_keys(room_id, sender)
        )
        removed = [key for key in keys if self._inbound.pop(key, None) is not None]
        if removed:
            self._flush()

    def senders(self, room_id: int) -> list[str]:
        prefix = f"{int(room_id)}{_SEP}"
        found: list[str] = []
        for key in self._inbound:
            if not key.startswith(prefix):
                continue
            sender = key[len(prefix):].rsplit(_SEP, 1)[0]
            if sender not in found:
                found.append(sender)
        return found

    def _chain_keys(self, room_id: int, sender: str) -> list[str]:
        """Keys of *sender*'s chains, oldest insertion first."""
        prefix = _inbound_prefix(room_id, sender)
        return [k for k in self._inbound if k.startswith(prefix)]


def get_sender_key_store(state: "AppState") -> SenderKeyStore | None:
    """Return the account's sender-key store, creating it lazily.

    Returns ``None`` when the identity key or account are unavailable (e.g.
    before the login key-restore completes).
    """
    cached = getattr(state, "sender_key_store", None)
    if cached is not None:
        return cached

    if state.x25519_private is None or state.current_user is None:
        return None

    store = SenderKeyStore(
        getattr(state, "secure_storage", None),
        state.x25519_private.private_bytes_raw(),
        state.current_user.username,
    )
    state.sender_key_store = store
    return store
