"""
Sender-Key group encryption (blob version 3).

Model
-----
Group (and public) rooms cannot use the pairwise Double Ratchet directly: an
N-member room would need N-1 ratchet encryptions per message. Instead every
*sender* owns a symmetric **sender chain** per room:

    chain_key_0  --HMAC-->  chain_key_1  --HMAC-->  chain_key_2 ...
         |                       |
        mk_0                    mk_1        (AES-256-GCM message keys)

The chain key is generated locally, distributed **once** to every room member
over the existing pairwise Double Ratchet (see ``crypto.group_session``), and
from then on each message costs a single symmetric encryption regardless of the
room size. Recipients ratchet their copy of the chain forward to derive the
same message key.

Security properties
-------------------
* **Forward secrecy within a chain** — message keys are derived with the same
  ``kdf_ck`` HMAC step used by the Double Ratchet and are burned once used, so
  a compromise of the current chain key does not reveal older messages.
* **Authentication** — every ciphertext is signed with the sender's long-term
  Ed25519 identity key and the signature is verified *before* any chain state
  is touched. A member cannot forge a message from another member even though
  everybody knows the chain key of the sender they receive from.
* **Post-compromise security / membership hygiene** — chains are rotated
  (fresh random chain key + new ``chain_id``) every
  ``ROTATION_MESSAGE_LIMIT`` messages and whenever the room membership changes
  (tracked server side by ``key_epoch``). A removed member therefore cannot
  read anything sent after their removal.
* **Replay / reordering** — the iteration number is authenticated as AAD, keys
  already consumed raise ``KeyConsumedError`` and out-of-order delivery is
  bounded by ``MAX_SKIP``.

This module is a pure state machine: no I/O, no storage, no network.
Persistence lives in ``crypto.sender_key_store`` and the distribution /
rotation orchestration lives in ``crypto.group_session``.
"""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crypto.double_ratchet import (
    KeyConsumedError,
    MissingChainError,
    TooFarAheadError,
    kdf_ck,
)

#: Blob version written into every group ciphertext.
SENDER_KEY_VERSION = 3

#: Rotate the sender chain after this many messages (requirement: every 100).
ROTATION_MESSAGE_LIMIT = 100

#: Bound on out-of-order delivery / stored skipped keys (DoS + memory guard).
MAX_SKIP = 1000

_KEY_LEN = 32


class UnknownSenderKeyError(MissingChainError):
    """No sender chain is available for this ciphertext (distribution missing)."""


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _new_chain_id() -> str:
    return os.urandom(16).hex()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class SenderKeyState:
    """One sender chain: either our own (outbound) or a peer's (inbound)."""

    room_id: int
    chain_id: str
    chain_key: bytes
    sender: str = ""
    iteration: int = 0
    key_epoch: int = 1
    #: Message keys derived while skipping over messages that have not arrived.
    skipped: dict[int, bytes] = field(default_factory=dict)

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "chain_id": self.chain_id,
            "chain_key": b64encode(self.chain_key).decode("ascii"),
            "sender": self.sender,
            "iteration": self.iteration,
            "key_epoch": self.key_epoch,
            "skipped": {
                str(i): b64encode(mk).decode("ascii") for i, mk in self.skipped.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SenderKeyState":
        return cls(
            room_id=int(data["room_id"]),
            chain_id=str(data["chain_id"]),
            chain_key=b64decode(data["chain_key"]),
            sender=str(data.get("sender", "")),
            iteration=int(data.get("iteration", 0)),
            key_epoch=int(data.get("key_epoch", 1)),
            skipped={
                int(i): b64decode(mk)
                for i, mk in (data.get("skipped") or {}).items()
            },
        )

    # -- chain arithmetic -------------------------------------------------

    def next_message_key(self) -> tuple[int, bytes]:
        """Advance the chain one step and return ``(iteration, message_key)``."""
        iteration = self.iteration
        self.chain_key, message_key = kdf_ck(self.chain_key)
        self.iteration = iteration + 1
        return iteration, message_key

    def message_key_for(self, iteration: int) -> bytes:
        """Return the message key for *iteration*, ratcheting/skipping as needed.

        Raises ``KeyConsumedError`` for an already-burned key (re-delivery or a
        re-render of old history) and ``TooFarAheadError`` when the gap exceeds
        ``MAX_SKIP``.
        """
        if iteration < 0:
            raise ValueError("iteration must be non-negative")

        if iteration < self.iteration:
            mk = self.skipped.pop(iteration, None)
            if mk is None:
                raise KeyConsumedError(
                    f"sender key {self.chain_id}:{iteration} already consumed"
                )
            return mk

        if iteration - self.iteration > MAX_SKIP:
            raise TooFarAheadError(
                f"sender key {self.chain_id}:{iteration} is more than "
                f"{MAX_SKIP} messages ahead"
            )

        # Store the keys of the messages we are skipping over so they can still
        # be decrypted when they arrive late.
        while self.iteration < iteration:
            i, mk = self.next_message_key()
            self.skipped[i] = mk
            if len(self.skipped) > MAX_SKIP:
                self.skipped.pop(min(self.skipped))

        _, message_key = self.next_message_key()
        return message_key

    def copy(self) -> "SenderKeyState":
        return SenderKeyState.from_dict(self.to_dict())


def new_sender_key(room_id: int, *, sender: str = "", key_epoch: int = 1) -> SenderKeyState:
    """Create a brand new outbound sender chain for *room_id*."""
    return SenderKeyState(
        room_id=int(room_id),
        chain_id=_new_chain_id(),
        chain_key=os.urandom(_KEY_LEN),
        sender=sender,
        iteration=0,
        key_epoch=int(key_epoch),
    )


def rotation_needed(state: SenderKeyState | None, key_epoch: int) -> bool:
    """True when a fresh chain must be created before sending.

    Rotation happens (a) every ``ROTATION_MESSAGE_LIMIT`` messages and (b) on
    any membership change, signalled by the server bumping the room's
    ``key_epoch``.
    """
    if state is None:
        return True
    if state.key_epoch != int(key_epoch):
        return True
    return state.iteration >= ROTATION_MESSAGE_LIMIT


# ---------------------------------------------------------------------------
# Message framing
# ---------------------------------------------------------------------------


def _header(blob: dict) -> dict:
    return {
        "v": SENDER_KEY_VERSION,
        "room": blob["room"],
        "cid": blob["cid"],
        "i": blob["i"],
        "s": blob.get("s", ""),
    }


def _header_ad(blob: dict) -> bytes:
    return _canonical(_header(blob))


def peek_group_header(blob_b64: str) -> dict | None:
    """Return the unauthenticated header of a v3 blob, or ``None``.

    Used to route an incoming ciphertext to the right sender chain *before* the
    signature can be checked. Nothing here is trusted: the values are only used
    for lookup, and the AEAD binds them as AAD.
    """
    try:
        blob = json.loads(b64decode(blob_b64).decode("utf-8"))
    except Exception:  # noqa: BLE001 - malformed blob is simply not v3
        return None
    if not isinstance(blob, dict) or int(blob.get("v", 0)) != SENDER_KEY_VERSION:
        return None
    try:
        return {
            "room_id": int(blob["room"]),
            "chain_id": str(blob["cid"]),
            "iteration": int(blob["i"]),
            "sender": str(blob.get("s", "")),
        }
    except (KeyError, TypeError, ValueError):
        return None


def encrypt_with_sender_key(
    plaintext: str,
    state: SenderKeyState,
    sender_ed25519_priv: Ed25519PrivateKey,
    *,
    sender: str | None = None,
) -> dict:
    """Encrypt *plaintext* with the next key of our own chain.

    Mutates *state* (the chain advances). Returns
    ``{"blob", "signature", "chain_id", "iteration", "key_epoch"}``.
    """
    handle = sender if sender is not None else state.sender
    iteration, message_key = state.next_message_key()

    nonce = os.urandom(12)
    blob_dict = {
        "v": SENDER_KEY_VERSION,
        "room": int(state.room_id),
        "cid": state.chain_id,
        "i": iteration,
        "s": handle,
        "nonce": b64encode(nonce).decode("ascii"),
        "ct": "",
    }
    blob_dict["ct"] = b64encode(
        AESGCM(message_key).encrypt(
            nonce, plaintext.encode("utf-8"), _header_ad(blob_dict)
        )
    ).decode("ascii")

    blob_bytes = _canonical(blob_dict)
    signature = sender_ed25519_priv.sign(blob_bytes)

    return {
        "blob": b64encode(blob_bytes).decode("ascii"),
        "signature": b64encode(signature).decode("ascii"),
        "chain_id": state.chain_id,
        "iteration": iteration,
        "key_epoch": state.key_epoch,
    }


def decrypt_with_sender_key(
    encrypted_msg: dict,
    state: SenderKeyState,
    sender_ed25519_pub: Ed25519PublicKey,
) -> str:
    """Verify and decrypt a v3 group ciphertext against *state*.

    *state* is mutated (chain advances / skipped keys are consumed), so callers
    should work on a copy and persist only after success.
    """
    blob_bytes = b64decode(encrypted_msg["blob"])
    signature_bytes = b64decode(encrypted_msg["signature"])

    # Authenticate before touching chain state — an attacker must not be able
    # to burn our keys or force skips with a forged header.
    sender_ed25519_pub.verify(signature_bytes, blob_bytes)

    blob = json.loads(blob_bytes.decode("utf-8"))
    if int(blob.get("v", 0)) != SENDER_KEY_VERSION:
        raise ValueError("not a sender-key (v3) blob")
    if str(blob["cid"]) != state.chain_id:
        raise UnknownSenderKeyError("ciphertext belongs to a different sender chain")
    if int(blob["room"]) != int(state.room_id):
        raise ValueError("ciphertext belongs to a different room")

    message_key = state.message_key_for(int(blob["i"]))
    plaintext = AESGCM(message_key).decrypt(
        b64decode(blob["nonce"]), b64decode(blob["ct"]), _header_ad(blob)
    )
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Distribution payloads (carried inside a pairwise Double Ratchet message)
# ---------------------------------------------------------------------------

DISTRIBUTION_TYPE = "sender_key"


def build_distribution_payload(state: SenderKeyState) -> str:
    """Serialize a chain so it can be shipped to one member.

    The payload is the *plaintext* of a pairwise Double Ratchet message, so the
    chain key never leaves the device unencrypted and inherits the ratchet's
    forward secrecy.
    """
    return json.dumps(
        {
            "t": DISTRIBUTION_TYPE,
            "v": SENDER_KEY_VERSION,
            "room_id": int(state.room_id),
            "chain_id": state.chain_id,
            "chain_key": b64encode(state.chain_key).decode("ascii"),
            "iteration": int(state.iteration),
            "key_epoch": int(state.key_epoch),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def parse_distribution_payload(payload: str, *, sender: str = "") -> SenderKeyState:
    """Rebuild an inbound chain from a decrypted distribution payload."""
    data = json.loads(payload)
    if data.get("t") != DISTRIBUTION_TYPE:
        raise ValueError("not a sender-key distribution payload")
    if int(data.get("v", 0)) != SENDER_KEY_VERSION:
        raise ValueError(f"unsupported sender-key version {data.get('v')}")
    chain_key = b64decode(data["chain_key"])
    if len(chain_key) != _KEY_LEN:
        raise ValueError("invalid chain key length")
    return SenderKeyState(
        room_id=int(data["room_id"]),
        chain_id=str(data["chain_id"]),
        chain_key=chain_key,
        sender=sender,
        iteration=int(data.get("iteration", 0)),
        key_epoch=int(data.get("key_epoch", 1)),
    )
