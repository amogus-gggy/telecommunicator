"""
Sender-key group encryption (Signal-style) for group rooms.

Each member keeps one sending chain per room: the chain key ratchets once per
message, and the whole chain is rotated (fresh key, next generation) every
``ROTATION_INTERVAL`` messages or whenever the roster changes. Every recipient
keeps a receiving chain per (room, sender, generation).

Distribution blobs wrap the chain key under each member's long-term X25519
identity key (the same ECDH wrap the v1 message scheme uses). Message blobs
are version 3; their plaintext payload is a JSON object carrying the visible
body plus per-file keys, so one ciphertext serves the whole room and file key
material federates inside the opaque blob.

Pure state machine + blob codecs — no I/O. Persistence lives in
``crypto.sender_key_store``; transport and distribution live in the views.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import sha256

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# A sending chain is rotated after this many messages.
ROTATION_INTERVAL = 500

# Bound on how far ahead a receive chain may be ratcheted (DoS/memory guard).
MAX_SKIP = 1000

# Message blob version for sender-key group messages.
MSG_VERSION = 3
# Distribution blob version.
DIST_VERSION = 1

_INFO_MSG = b"tlc-sender-key-v1-msg"
_INFO_DIST = b"tlc-sender-key-dist-v1"

_KEY_LEN = 32


class SenderKeyError(Exception):
    """Base class for sender-key failures."""


class KeyConsumedError(SenderKeyError):
    """The receiving chain already advanced past this message index."""


class TooFarAheadError(SenderKeyError):
    """The message index is more than MAX_SKIP ahead of the stored chain."""


class UnknownGenerationError(SenderKeyError):
    """No receiving chain is known for the blob's generation."""


class DistributionError(SenderKeyError):
    """A distribution blob could not be unwrapped."""


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def serialize_blob(blob_dict: dict) -> bytes:
    """Canonical bytes of a message blob — the data that gets signed."""
    return _canonical(blob_dict)


def roster_digest(participants: list[str]) -> str:
    """Stable digest of a roster — any join/leave changes it."""
    joined = "\n".join(sorted(set(participants)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass
class SenderChainState:
    """One ratcheting chain. Serializable to a JSON-safe dict."""

    generation: int
    iteration: int  # messages consumed under this generation
    chain_key: bytes  # raw 32 bytes

    def to_dict(self) -> dict:
        return {
            "generation": self.generation,
            "iteration": self.iteration,
            "chain_key": b64encode(self.chain_key).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SenderChainState":
        return cls(
            generation=int(data["generation"]),
            iteration=int(data["iteration"]),
            chain_key=b64decode(data["chain_key"]),
        )


def create_chain(generation: int = 0) -> SenderChainState:
    return SenderChainState(
        generation=generation, iteration=0, chain_key=os.urandom(_KEY_LEN)
    )


def rotate_chain(current: SenderChainState | None) -> SenderChainState:
    """Fresh chain in the next generation (generation 0 when starting out)."""
    generation = 0 if current is None else current.generation + 1
    return create_chain(generation)


def advance_chain(
    state: SenderChainState, target: int
) -> tuple[bytes, SenderChainState]:
    """Ratchet the chain to ``target`` and consume that iteration.

    Returns ``(message_key, new_state)`` where ``new_state.iteration ==
    target + 1``. Message keys are burned: re-requesting a consumed index
    raises ``KeyConsumedError``.
    """
    if target < state.iteration:
        raise KeyConsumedError(
            f"iteration {target} already consumed (chain at {state.iteration})"
        )
    if target - state.iteration > MAX_SKIP:
        raise TooFarAheadError(
            f"iteration {target} is more than {MAX_SKIP} ahead"
        )

    chain_key = state.chain_key
    for _ in range(state.iteration, target):
        chain_key = _hmac.new(chain_key, b"\x02", sha256).digest()
    message_key = _hmac.new(chain_key, b"\x01", sha256).digest()
    next_chain_key = _hmac.new(chain_key, b"\x02", sha256).digest()

    return message_key, SenderChainState(
        generation=state.generation,
        iteration=target + 1,
        chain_key=next_chain_key,
    )


def _message_ad(*, generation: int, n: int) -> bytes:
    # Room/sender are intentionally NOT bound here: federated mirrors address
    # the same message with different room ids and sender handles.  Binding is
    # provided by the per-(room, sender) chain lookup instead.
    return _canonical({"v": MSG_VERSION, "gen": generation, "n": n})


def encrypt_group_message(
    state: SenderChainState,
    payload_bytes: bytes,
) -> tuple[dict, bytes, SenderChainState]:
    """Encrypt one group message at the chain's current iteration.

    Returns ``(blob_dict, message_key, new_state)``. ``blob_dict`` is the
    v3 recipient blob (not yet canonicalized/signed); ``message_key`` lets the
    caller build the sender's own stateless copy.
    """
    n = state.iteration
    message_key, new_state = advance_chain(state, n)

    nonce = os.urandom(12)
    ad = _message_ad(generation=state.generation, n=n)
    ct = AESGCM(message_key).encrypt(nonce, payload_bytes, ad)

    blob_dict = {
        "v": MSG_VERSION,
        "gen": state.generation,
        "n": n,
        "nonce": b64encode(nonce).decode("ascii"),
        "ct": b64encode(ct).decode("ascii"),
    }
    return blob_dict, message_key, new_state


def decrypt_group_message(
    blob_b64: str,
    chain: SenderChainState,
) -> tuple[bytes, SenderChainState]:
    """Decrypt a v3 blob with the matching receive chain.

    Raises ``UnknownGenerationError`` when the blob's generation differs from
    the chain's (caller should fetch that generation's distribution blob), and
    propagates ``KeyConsumedError`` / ``TooFarAheadError`` otherwise.
    """
    try:
        blob = json.loads(b64decode(blob_b64).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SenderKeyError("malformed group message blob") from exc

    if int(blob.get("v", 0)) != MSG_VERSION:
        raise SenderKeyError("not a group (v3) blob")
    generation = int(blob["gen"])
    if generation != chain.generation:
        raise UnknownGenerationError(
            f"blob generation {generation}, chain at {chain.generation}"
        )

    n = int(blob["n"])
    message_key, new_chain = advance_chain(chain, n)
    nonce = b64decode(blob["nonce"])
    ct = b64decode(blob["ct"])
    ad = _message_ad(generation=generation, n=n)
    try:
        payload = AESGCM(message_key).decrypt(nonce, ct, ad)
    except InvalidTag as exc:
        raise SenderKeyError("group message authentication failed") from exc
    return payload, new_chain


# ---------------------------------------------------------------------------
# Distribution blobs — chain keys wrapped under a member's identity X25519 key
# ---------------------------------------------------------------------------


def _derive_wrapping_key(
    shared_secret: bytes, ephemeral_pub: bytes, peer_pub: bytes
) -> bytes:
    salt = ephemeral_pub + peer_pub
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=_INFO_DIST
    ).derive(shared_secret)


def peek_group_generation(blob_b64: str) -> int | None:
    """Return the generation of a v3 blob without decrypting, or None."""
    try:
        blob = json.loads(b64decode(blob_b64).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if int(blob.get("v", 0)) != MSG_VERSION:
        return None
    return int(blob["gen"])


def wrap_distribution(
    chain: SenderChainState,
    recipient_x25519_pub: X25519PublicKey,
) -> str:
    """Wrap the chain key under one member's identity X25519 key; returns b64."""
    payload = _canonical(
        {
            "v": DIST_VERSION,
            "t": "sender-key",
            "gen": chain.generation,
            "ck": b64encode(chain.chain_key).decode("ascii"),
        }
    )

    ephemeral_priv = X25519PrivateKey.generate()
    ephemeral_pub = ephemeral_priv.public_key().public_bytes_raw()
    recipient_pub = recipient_x25519_pub.public_bytes_raw()

    shared_secret = ephemeral_priv.exchange(recipient_x25519_pub)
    wrapping_key = _derive_wrapping_key(shared_secret, ephemeral_pub, recipient_pub)

    nonce = os.urandom(12)
    ct = AESGCM(wrapping_key).encrypt(nonce, payload, None)

    blob = _canonical(
        {
            "v": DIST_VERSION,
            "ephemeral_pub": b64encode(ephemeral_pub).decode("ascii"),
            "ct": b64encode(nonce + ct).decode("ascii"),
        }
    )
    return b64encode(blob).decode("ascii")


def unwrap_distribution(
    blob_b64: str,
    recipient_x25519_priv: X25519PrivateKey,
) -> SenderChainState:
    """Unwrap a distribution blob into a receive chain at iteration 0."""
    try:
        blob = json.loads(b64decode(blob_b64).decode("utf-8"))
        ephemeral_pub = X25519PublicKey.from_public_bytes(
            b64decode(blob["ephemeral_pub"])
        )
        raw = b64decode(blob["ct"])
        nonce, ct = raw[:12], raw[12:]
    except Exception as exc:  # noqa: BLE001
        raise DistributionError("malformed distribution blob") from exc

    shared_secret = recipient_x25519_priv.exchange(ephemeral_pub)
    wrapping_key = _derive_wrapping_key(
        shared_secret,
        ephemeral_pub.public_bytes_raw(),
        recipient_x25519_priv.public_key().public_bytes_raw(),
    )
    try:
        payload = json.loads(AESGCM(wrapping_key).decrypt(nonce, ct, None))
    except Exception as exc:  # noqa: BLE001
        raise DistributionError("distribution blob unwrap failed") from exc

    if int(payload.get("v", 0)) != DIST_VERSION or payload.get("t") != "sender-key":
        raise DistributionError("not a sender-key distribution blob")

    return SenderChainState(
        generation=int(payload["gen"]),
        iteration=0,
        chain_key=b64decode(payload["ck"]),
    )
