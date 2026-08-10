"""
Encrypted-at-rest helpers for locally persisted E2EE material.

Both the ratchet session store and the plaintext message store persist data to
the plaintext ``LocalStorage`` (which is not encrypted). This module provides a
seal/open wrapper: values are JSON-serialized then AES-256-GCM encrypted under
a key derived from the account's identity X25519 private key. The identity key
is restored from the server backup at every login, so no extra user input is
needed and the on-disk file is useless without the account key.
"""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_SIZE = 12
_SALT = b"tlc-at-rest-salt-v1"


def derive_storage_key(
    identity_x25519_priv_raw: bytes, account: str, purpose: str
) -> bytes:
    """Derive a purpose-scoped AES key from the account's identity key."""
    info = f"tlc-at-rest-v1:{purpose}:{account}".encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_SALT, info=info
    ).derive(identity_x25519_priv_raw)


def seal(key: bytes, obj: Any) -> str:
    """Encrypt a JSON-serializable object to a base64 string."""
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    nonce = os.urandom(_NONCE_SIZE)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return b64encode(nonce + ct).decode("ascii")


def open_value(key: bytes, value: str | None) -> Any | None:
    """Decrypt a base64 string back to a JSON object, or None on any failure."""
    if not value:
        return None
    try:
        raw = b64decode(value)
        nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        data = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None
