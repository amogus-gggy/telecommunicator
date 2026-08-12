"""
Per-peer Double Ratchet session persistence.

Sessions are keyed by the peer handle (the same username string used on the
send and receive paths) and persisted to ``LocalStorage`` encrypted at rest.
State is written through on every ``put`` so a restarted client can continue an
existing ratchet conversation and decrypt new messages.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from crypto.at_rest import derive_storage_key, open_value, seal
from crypto.double_ratchet import RatchetState

if TYPE_CHECKING:
    from state import AppState

logger = logging.getLogger(__name__)

_PURPOSE = "ratchet-sessions"


class RatchetSessionStore:
    """Loads/persists ratchet sessions for one account."""

    def __init__(self, storage: Any, identity_x25519_priv_raw: bytes, account: str):
        self._storage = storage
        self._account = account
        self._store_key = f"ratchet_sessions.{account}"
        self._key = derive_storage_key(identity_x25519_priv_raw, account, _PURPOSE)
        self._sessions: dict[str, RatchetState] = self._load()

    def _load(self) -> dict[str, RatchetState]:
        raw = self._storage.get(self._store_key) if self._storage is not None else None
        data = open_value(self._key, raw)
        sessions: dict[str, RatchetState] = {}
        if not isinstance(data, dict):
            return sessions
        for peer, state_dict in data.items():
            try:
                sessions[peer] = RatchetState.from_dict(state_dict)
            except Exception as exc:  # noqa: BLE001 - tolerate corrupt entry
                logger.warning("[RatchetStore] dropping corrupt session %r: %s", peer, exc)
        return sessions

    def _flush(self) -> None:
        if self._storage is None:
            return
        payload = {peer: st.to_dict() for peer, st in self._sessions.items()}
        self._storage.set(self._store_key, seal(self._key, payload))

    def get(self, peer: str) -> RatchetState | None:
        return self._sessions.get(peer)

    def put(self, peer: str, st: RatchetState) -> None:
        self._sessions[peer] = st
        self._flush()

    def delete(self, peer: str) -> None:
        if peer in self._sessions:
            del self._sessions[peer]
            self._flush()

    def peers(self) -> list[str]:
        return list(self._sessions.keys())


def get_session_store(state: "AppState") -> RatchetSessionStore | None:
    """Return the account's session store, creating it lazily.

    Returns ``None`` when the identity key, account, or storage are unavailable
    (e.g. before login restore completes).
    """
    cached = getattr(state, "ratchet_sessions", None)
    if cached is not None:
        return cached

    if state.x25519_private is None or state.current_user is None:
        return None
    storage = getattr(state, "secure_storage", None)

    store = RatchetSessionStore(
        storage,
        state.x25519_private.private_bytes_raw(),
        state.current_user.username,
    )
    state.ratchet_sessions = store
    return store
