"""
Per-room sender-key persistence.

Own sending chains are keyed by room id; receiving chains are keyed by
``(room_id, sender_handle)`` with the last ``_KEEP_GENERATIONS`` generations
kept so in-flight messages from a just-rotated sender still decrypt. The whole
structure is sealed at rest under the account's identity key, mirroring
``crypto.ratchet_session_store``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from crypto.at_rest import derive_storage_key, open_value, seal
from crypto.sender_keys import SenderChainState

if TYPE_CHECKING:
    from state import AppState

logger = logging.getLogger(__name__)

_PURPOSE = "sender-keys"
_KEEP_GENERATIONS = 3


def _peer_key(room_id: int, sender: str) -> str:
    return f"{room_id}:{sender}"


class SenderKeyStore:
    """Loads/persists sender-key chains for one account."""

    def __init__(self, storage: Any, identity_x25519_priv_raw: bytes, account: str):
        self._storage = storage
        self._account = account
        self._store_key = f"sender_keys.{account}"
        self._key = derive_storage_key(identity_x25519_priv_raw, account, _PURPOSE)
        self._own: dict[int, SenderChainState] = {}
        self._rosters: dict[int, str] = {}
        self._peers: dict[str, list[SenderChainState]] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        raw = self._storage.get(self._store_key) if self._storage is not None else None
        data = open_value(self._key, raw)
        if not isinstance(data, dict):
            return
        for room_id, chain in (data.get("own") or {}).items():
            try:
                self._own[int(room_id)] = SenderChainState.from_dict(chain)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SenderKeyStore] dropping own chain %r: %s", room_id, exc)
        for room_id, digest in (data.get("rosters") or {}).items():
            if isinstance(digest, str):
                self._rosters[int(room_id)] = digest
        for key, chains in (data.get("peers") or {}).items():
            loaded: list[SenderChainState] = []
            for chain in chains or []:
                try:
                    loaded.append(SenderChainState.from_dict(chain))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[SenderKeyStore] dropping chain %r: %s", key, exc)
            if loaded:
                self._peers[key] = loaded

    def _flush(self) -> None:
        if self._storage is None:
            return
        payload = {
            "own": {str(r): st.to_dict() for r, st in self._own.items()},
            "rosters": {str(r): d for r, d in self._rosters.items()},
            "peers": {
                key: [st.to_dict() for st in chains]
                for key, chains in self._peers.items()
            },
        }
        self._storage.set(self._store_key, seal(self._key, payload))

    # -- own sending chains --------------------------------------------------

    def get_own(self, room_id: int) -> SenderChainState | None:
        return self._own.get(room_id)

    def put_own(self, room_id: int, state: SenderChainState) -> None:
        self._own[room_id] = state
        self._flush()

    def delete_own(self, room_id: int) -> None:
        if room_id in self._own:
            del self._own[room_id]
            self._flush()

    # -- roster digests (rotation trigger) -----------------------------------

    def get_roster(self, room_id: int) -> str | None:
        return self._rosters.get(room_id)

    def put_roster(self, room_id: int, digest: str) -> None:
        self._rosters[room_id] = digest
        self._flush()

    # -- receiving chains ------------------------------------------------------

    def get_peer(
        self, room_id: int, sender: str, generation: int
    ) -> SenderChainState | None:
        for chain in self._peers.get(_peer_key(room_id, sender), []):
            if chain.generation == generation:
                return chain
        return None

    def put_peer(self, room_id: int, sender: str, state: SenderChainState) -> None:
        key = _peer_key(room_id, sender)
        chains = [
            c for c in self._peers.get(key, []) if c.generation != state.generation
        ]
        chains.append(state)
        chains.sort(key=lambda c: c.generation)
        self._peers[key] = chains[-_KEEP_GENERATIONS:]
        self._flush()

    def delete_room(self, room_id: int) -> None:
        """Drop all sender-key state for a room (leave/remove)."""
        self._own.pop(room_id, None)
        self._rosters.pop(room_id, None)
        prefix = f"{room_id}:"
        for key in [k for k in self._peers if k.startswith(prefix)]:
            del self._peers[key]
        self._flush()


def get_sender_key_store(state: "AppState") -> SenderKeyStore | None:
    """Return the account's sender-key store, creating it lazily.

    Returns ``None`` when the identity key, account, or storage are unavailable
    (e.g. before login restore completes).
    """
    cached = getattr(state, "sender_key_store", None)
    if cached is not None:
        return cached

    if state.x25519_private is None or state.current_user is None:
        return None
    storage = getattr(state, "secure_storage", None)

    store = SenderKeyStore(
        storage,
        state.x25519_private.private_bytes_raw(),
        state.current_user.username,
    )
    state.sender_key_store = store
    return store
