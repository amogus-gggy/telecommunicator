"""Proof-of-Work anti-bot challenges for login/registration.

The server issues a short-lived, single-use challenge. The client must find a
nonce such that ``sha256(f"{challenge}:{nonce}")`` in hex starts with
``difficulty`` zero characters. This makes scripted mass account creation or
login brute-force significantly more expensive.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time

POW_REQUIRED: bool = os.getenv("POW_REQUIRED", "true").lower() in (
    "1",
    "true",
    "yes",
)
POW_DIFFICULTY: int = int(os.getenv("POW_DIFFICULTY", "4"))
POW_TTL_SECONDS: int = int(os.getenv("POW_TTL_SECONDS", "300"))

# challenge -> (expires_at_epoch, difficulty)
_pending: dict[str, tuple[float, int]] = {}


def issue_challenge() -> dict:
    _gc()
    challenge = secrets.token_hex(16)
    _pending[challenge] = (time.monotonic() + POW_TTL_SECONDS, POW_DIFFICULTY)
    return {"challenge": challenge, "difficulty": POW_DIFFICULTY}


def verify_pow(challenge: str | None, nonce: str | None) -> bool:
    _gc()
    if not POW_REQUIRED:
        return True
    if not challenge or nonce is None:
        return False
    record = _pending.pop(challenge, None)
    if record is None:
        return False
    expires, difficulty = record
    if time.monotonic() > expires:
        return False
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode()).hexdigest()
    return digest.startswith("0" * difficulty)


def _gc() -> None:
    now = time.monotonic()
    expired = [c for c, (exp, _) in _pending.items() if exp < now]
    for c in expired:
        _pending.pop(c, None)
