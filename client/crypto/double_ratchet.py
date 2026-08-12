"""
Signal-style Double Ratchet for E2EE messaging.

Provides forward secrecy *and* post-compromise security ("future secrecy"):
message keys are burned as the chain advances, and each new Diffie-Hellman
ratchet step mixes fresh entropy so a compromised session heals itself once
the peers exchange a new ratchet public key.

This module is a pure state machine — no I/O, no storage. Persistence is the
responsibility of ``crypto.ratchet_session_store``. Transport framing (blob /
signature) is handled by ``crypto.ratchet_facade``.

Algorithm follows the Signal Double Ratchet specification, adapted to this
codebase:

* ``KDF_CK``  — symmetric chain-key step (HMAC-SHA256).
* ``KDF_RK``  — root-key step (HKDF-SHA256 over a DH output).
* ``init_alice`` / ``init_bob`` — session bootstrap off the peers' published
  long-term X25519 keys (convergence via X25519 commutativity).
* ``ratchet_encrypt`` / ``ratchet_decrypt`` — per-message send/receive with
  skipped-message-key handling for out-of-order delivery and the PN field for
  DH ratchet steps mid-chain.
"""

from __future__ import annotations

import hmac as _hmac
from base64 import b64decode, b64encode
from dataclasses import dataclass, field
from hashlib import sha256

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Domain-separation info strings for the KDFs.
_INFO_INIT = b"tlc-ratchet-v2-init"
_INFO_ROOT = b"tlc-ratchet-v2-root"

# Bound on out-of-order distance / stored skipped keys (DoS + memory guard).
MAX_SKIP = 1000

_KEY_LEN = 32


class RatchetError(Exception):
    """Base class for ratchet failures."""


class KeyConsumedError(RatchetError):
    """The message key for this index was already burned (re-delivery/old page)."""


class TooFarAheadError(RatchetError):
    """The requested message index exceeds MAX_SKIP."""


class MissingChainError(RatchetError):
    """Cannot advance a chain that has not been established."""


def _hkdf(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=salt, info=info
    ).derive(ikm)


def kdf_ck(chain_key: bytes) -> tuple[bytes, bytes]:
    """Symmetric chain-key ratchet step.

    Returns ``(next_chain_key, message_key)``.
    """
    message_key = _hmac.new(chain_key, b"\x01", sha256).digest()
    next_chain_key = _hmac.new(chain_key, b"\x02", sha256).digest()
    return next_chain_key, message_key


def kdf_rk(root_key: bytes, dh_output: bytes) -> tuple[bytes, bytes]:
    """Root-key ratchet step.

    Returns ``(new_root_key, new_chain_key)``.
    """
    out = _hkdf(dh_output, root_key, _INFO_ROOT, 64)
    return out[:_KEY_LEN], out[_KEY_LEN:]


def _generate_dh() -> tuple[bytes, bytes]:
    """Generate an X25519 ratchet keypair, returning ``(priv_raw, pub_raw)``."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key()
    return priv.private_bytes_raw(), pub.public_bytes_raw()


def _dh(priv_raw: bytes, peer_pub_raw: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(priv_raw)
    peer_pub = X25519PublicKey.from_public_bytes(peer_pub_raw)
    return priv.exchange(peer_pub)


def derive_initial_shared_secret(
    my_x25519_priv_raw: bytes, peer_x25519_pub_raw: bytes
) -> bytes:
    """Bootstrap shared secret from the peers' published long-term keys."""
    return _hkdf(_dh(my_x25519_priv_raw, peer_x25519_pub_raw), b"\x00" * 32, _INFO_INIT, _KEY_LEN)


@dataclass
class RatchetState:
    """Full per-peer Double Ratchet state. Serializable to a JSON-safe dict."""

    peer_identity_pub: bytes
    root_key: bytes
    dh_priv: bytes | None = None
    dh_pub: bytes | None = None
    remote_dh: bytes | None = None
    ck_send: bytes | None = None
    ck_recv: bytes | None = None
    n_s: int = 0
    n_r: int = 0
    pn: int = 0
    # key: f"{b64(remote_dh)}:{n}" -> message key
    skipped: dict[str, bytes] = field(default_factory=dict)

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict:
        def b(v: bytes | None) -> str | None:
            return b64encode(v).decode("ascii") if v is not None else None

        return {
            "peer_identity_pub": b(self.peer_identity_pub),
            "root_key": b(self.root_key),
            "dh_priv": b(self.dh_priv),
            "dh_pub": b(self.dh_pub),
            "remote_dh": b(self.remote_dh),
            "ck_send": b(self.ck_send),
            "ck_recv": b(self.ck_recv),
            "n_s": self.n_s,
            "n_r": self.n_r,
            "pn": self.pn,
            "skipped": {k: b64encode(v).decode("ascii") for k, v in self.skipped.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RatchetState":
        def ub(v: str | None) -> bytes | None:
            return b64decode(v) if v is not None else None

        return cls(
            peer_identity_pub=ub(d["peer_identity_pub"]),
            root_key=ub(d["root_key"]),
            dh_priv=ub(d.get("dh_priv")),
            dh_pub=ub(d.get("dh_pub")),
            remote_dh=ub(d.get("remote_dh")),
            ck_send=ub(d.get("ck_send")),
            ck_recv=ub(d.get("ck_recv")),
            n_s=int(d.get("n_s", 0)),
            n_r=int(d.get("n_r", 0)),
            pn=int(d.get("pn", 0)),
            skipped={
                k: b64decode(v) for k, v in d.get("skipped", {}).items()
            },
        )


def _skip_key(st: RatchetState, dh: bytes, n: int) -> str:
    return f"{b64encode(dh).decode('ascii')}:{n}"


def init_alice(
    my_x25519_priv_raw: bytes, peer_x25519_pub_raw: bytes
) -> RatchetState:
    """Initiator bootstrap: we send the first message of the session.

    Uses the peer's published long-term X25519 key as their initial ratchet
    public key, then performs one sending DH ratchet step.
    """
    sk = derive_initial_shared_secret(my_x25519_priv_raw, peer_x25519_pub_raw)
    st = RatchetState(peer_identity_pub=peer_x25519_pub_raw, root_key=sk)
    st.dh_priv, st.dh_pub = _generate_dh()
    st.remote_dh = peer_x25519_pub_raw
    st.root_key, st.ck_send = kdf_rk(st.root_key, _dh(st.dh_priv, st.remote_dh))
    return st


def init_bob(
    my_x25519_priv_raw: bytes,
    peer_identity_pub_raw: bytes,
    header_dh: bytes,
) -> RatchetState:
    """Responder bootstrap: we received the session's first message.

    ``my_x25519_priv_raw`` is our published long-term key (our initial ratchet
    private key); ``header_dh`` is the initiator's ratchet public key from the
    incoming message header. Sets up the receiving chain, then performs a
    sending DH ratchet step so the session is ready to reply.
    """
    sk = derive_initial_shared_secret(my_x25519_priv_raw, peer_identity_pub_raw)
    st = RatchetState(peer_identity_pub=peer_identity_pub_raw, root_key=sk)
    # Receiving DH ratchet step against the initiator's ratchet key.
    st.remote_dh = header_dh
    st.root_key, st.ck_recv = kdf_rk(st.root_key, _dh(my_x25519_priv_raw, st.remote_dh))
    # Sending DH ratchet step so we can reply.
    st.dh_priv, st.dh_pub = _generate_dh()
    st.root_key, st.ck_send = kdf_rk(st.root_key, _dh(st.dh_priv, st.remote_dh))
    return st


def ratchet_encrypt(st: RatchetState, plaintext: bytes) -> tuple[dict, bytes]:
    """Encrypt ``plaintext`` on the current sending chain.

    Returns ``(header, message_key)`` where ``header`` is a JSON-safe dict
    ``{"dh","pn","n"}`` (all values primitives/b64 strings) and ``message_key``
    is the raw key the caller uses for AEAD. Advances ``n_s``.

    The caller performs the AEAD encryption so it can also wrap the same
    message key for the sender's own copy.
    """
    if st.ck_send is None:
        raise MissingChainError("Sending chain not established")

    st.ck_send, message_key = kdf_ck(st.ck_send)
    header = {
        "dh": b64encode(st.dh_pub).decode("ascii"),
        "pn": st.pn,
        "n": st.n_s,
    }
    st.n_s += 1
    return header, message_key


def _skip_message_keys(st: RatchetState, until: int) -> None:
    """Derive and stash receiving-chain message keys from ``n_r`` to ``until``."""
    if until > st.n_r + MAX_SKIP:
        raise TooFarAheadError(f"cannot skip to message index {until}")
    if until <= st.n_r:
        return
    if st.ck_recv is None:
        raise MissingChainError("Receiving chain not established")
    while st.n_r < until:
        st.ck_recv, mk = kdf_ck(st.ck_recv)
        st.skipped[_skip_key(st, st.remote_dh, st.n_r)] = mk
        st.n_r += 1


def ratchet_decrypt(st: RatchetState, header: dict, expected_index: int | None = None) -> bytes:
    """Resolve the message key for an incoming message, advancing state.

    ``header`` must contain ``dh`` (b64 peer ratchet pub), ``pn`` (int) and
    ``n`` (int). Returns the raw message key for AEAD decryption. Raises
    :class:`KeyConsumedError` if the key was already burned.
    """
    peer_dh = b64decode(header["dh"])
    pn = int(header["pn"])
    n = int(header["n"])

    # 1. Try a previously skipped key.
    sk_key = _skip_key(st, peer_dh, n)
    if sk_key in st.skipped:
        mk = st.skipped.pop(sk_key)
        return mk

    # 2. New DH ratchet key from the peer -> perform DH ratchet steps.
    if st.remote_dh is None or peer_dh != st.remote_dh:
        # Preserve unread keys from the peer's previous sending chain.
        _skip_message_keys(st, pn)
        st.pn = st.n_s
        st.n_s = 0
        st.n_r = 0
        st.remote_dh = peer_dh
        if st.dh_priv is None:
            raise MissingChainError("No local ratchet key for DH step")
        st.root_key, st.ck_recv = kdf_rk(st.root_key, _dh(st.dh_priv, st.remote_dh))
        # Sending ratchet step so our next reply rotates the ratchet.
        st.dh_priv, st.dh_pub = _generate_dh()
        st.root_key, st.ck_send = kdf_rk(st.root_key, _dh(st.dh_priv, st.remote_dh))

    # 3. Skip forward within the receiving chain to reach message index n.
    if n < st.n_r:
        raise KeyConsumedError(f"message index {n} already consumed")
    _skip_message_keys(st, n)

    # 4. The next chain step yields the message key for index n.
    if st.ck_recv is None:
        raise MissingChainError("Receiving chain not established")
    st.ck_recv, mk = kdf_ck(st.ck_recv)
    st.n_r += 1
    return mk
