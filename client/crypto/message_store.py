"""
Local persistence of decrypted message bodies.

The Double Ratchet burns message keys as it advances, so a message received and
decrypted today cannot be re-derived after the chain moves on. To keep DM
history readable across restarts and history paging, each successfully decrypted
body is persisted here, encrypted at rest under the account's identity key.

This mirrors how production E2EE messengers work: the ratchet protects messages
in transit / on the server, while the client keeps its own decrypted copy.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from crypto.at_rest import derive_storage_key, open_value, seal

if TYPE_CHECKING:
    from state import AppState

logger = logging.getLogger(__name__)

_PURPOSE = "msg-plaintext"
_MAX_ENTRIES = 5000


class PlaintextMessageStore:
    """Stores decrypted message bodies keyed by message id, encrypted at rest."""

    def __init__(self, storage: Any, identity_x25519_priv_raw: bytes, account: str):
        self._storage = storage
        self._store_key = f"msg_plaintext.{account}"
        self._key = derive_storage_key(identity_x25519_priv_raw, account, _PURPOSE)
        self._messages: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        raw = self._storage.get(self._store_key) if self._storage is not None else None
        data = open_value(self._key, raw)
        if not isinstance(data, dict):
            return {}
        return {k: str(v) for k, v in data.items()}

    def _flush(self) -> None:
        if self._storage is None:
            return
        self._storage.set(self._store_key, seal(self._key, self._messages))

    def get(self, msg_id: int | str) -> str | None:
        return self._messages.get(str(msg_id))

    def put(self, msg_id: int | str, body: str) -> None:
        key = str(msg_id)
        if key in self._messages:
            self._messages[key] = body
        else:
            self._messages[key] = body
            if len(self._messages) > _MAX_ENTRIES:
                # Drop oldest-inserted entries to bound disk usage.
                for old_key in list(self._messages)[: len(self._messages) - _MAX_ENTRIES]:
                    del self._messages[old_key]
        self._flush()

    def has(self, msg_id: int | str) -> bool:
        return str(msg_id) in self._messages


def get_message_store(state: "AppState") -> PlaintextMessageStore | None:
    """Return the account's plaintext message store, creating it lazily."""
    cached = getattr(state, "message_store", None)
    if cached is not None:
        return cached

    if state.x25519_private is None or state.current_user is None:
        return None
    storage = getattr(state, "secure_storage", None)

    store = PlaintextMessageStore(
        storage,
        state.x25519_private.private_bytes_raw(),
        state.current_user.username,
    )
    state.message_store = store
    return store
