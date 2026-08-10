"""
High-level Double Ratchet encrypt/decrypt facade.

Keeps the existing ``{"blob", "sender_blob", "signature"}`` transport contract
so the rest of the app needs minimal changes. The recipient blob carries the
ratchet header (version 2); the sender's own copy stays in the version-1 shape
(self-contained, wrapped under the sender's long-term key) so
``MessageDecryptor.decrypt_own_message`` works unchanged.

Security properties:
* The Ed25519 signature is verified before ANY ratchet state is touched, so an
  attacker cannot force re-initialization without the peer's signing key.
* Speculative decryption runs on a deep copy; state is only persisted after a
  successful AEAD check.
* On decrypt failure the session is healed by re-initializing as responder,
  which recovers from simultaneous-init races and peer state loss.
"""

from __future__ import annotations

import copy
import json
import os
from base64 import b64decode, b64encode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crypto.double_ratchet import (
    init_alice,
    init_bob,
    ratchet_decrypt,
    ratchet_encrypt,
)
from crypto.message_crypto import MessageEncryptor
from crypto.ratchet_session_store import RatchetSessionStore

_VERSION = 2


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def peek_blob_version(blob_b64: str) -> int:
    """Return the ``v`` field of a recipient blob, defaulting to 1 (legacy)."""
    try:
        blob = json.loads(b64decode(blob_b64).decode("utf-8"))
        return int(blob.get("v", 1))
    except Exception:  # noqa: BLE001 - malformed blob treated as legacy
        return 1


def _header_ad(blob: dict) -> bytes:
    return _canonical(
        {"v": _VERSION, "dh": blob["dh"], "pn": blob["pn"], "n": blob["n"]}
    )


class RatchetEncryptor:
    """Encrypts a message using the per-peer Double Ratchet session."""

    def encrypt_message(
        self,
        plaintext: str,
        *,
        peer_key: str,
        peer_identity_x25519_pub: X25519PublicKey,
        sender_ed25519_priv: Ed25519PrivateKey,
        sender_x25519_priv: X25519PrivateKey,
        sender_id: str,
        recipient_id: str,
        store: RatchetSessionStore | None,
    ) -> dict:
        """Return ``{"blob", "sender_blob", "signature"}`` (all base64)."""
        my_priv_raw = sender_x25519_priv.private_bytes_raw()
        peer_pub_raw = peer_identity_x25519_pub.public_bytes_raw()

        st = store.get(peer_key) if store else None
        if st is None:
            st = init_alice(my_priv_raw, peer_pub_raw)

        header, message_key = ratchet_encrypt(st, plaintext.encode("utf-8"))
        plaintext_bytes = plaintext.encode("utf-8")

        # Recipient copy: ratchet header + AEAD bound to the header.
        nonce_r = os.urandom(12)
        blob_dict = {
            "v": _VERSION,
            "dh": header["dh"],
            "pn": header["pn"],
            "n": header["n"],
            "nonce": b64encode(nonce_r).decode("ascii"),
            "ct": b64encode(
                AESGCM(message_key).encrypt(nonce_r, plaintext_bytes, _header_ad(
                    {"dh": header["dh"], "pn": header["pn"], "n": header["n"], "v": _VERSION}
                ))
            ).decode("ascii"),
        }
        blob_bytes = _canonical(blob_dict)
        signature = sender_ed25519_priv.sign(blob_bytes)

        # Sender copy: version-1 shape wrapping the SAME ratchet message key
        # under the sender's long-term key so own-message decrypt stays stateless.
        sender_blob_bytes = self._build_sender_blob(
            message_key,
            plaintext_bytes,
            sender_x25519_priv,
            sender_id,
            recipient_id,
        )

        if store is not None:
            store.put(peer_key, st)

        return {
            "blob": b64encode(blob_bytes).decode("ascii"),
            "sender_blob": b64encode(sender_blob_bytes).decode("ascii"),
            "signature": b64encode(signature).decode("ascii"),
        }

    @staticmethod
    def _build_sender_blob(
        message_key: bytes,
        plaintext_bytes: bytes,
        sender_x25519_priv: X25519PrivateKey,
        sender_id: str,
        recipient_id: str,
    ) -> bytes:
        ephemeral_priv = X25519PrivateKey.generate()
        ephemeral_pub_bytes = ephemeral_priv.public_key().public_bytes_raw()
        sender_pub_bytes = sender_x25519_priv.public_key().public_bytes_raw()

        shared_secret = ephemeral_priv.exchange(sender_x25519_priv.public_key())
        wrapping_key = MessageEncryptor._derive_wrapping_key(
            shared_secret, ephemeral_pub_bytes, sender_pub_bytes
        )

        nonce_wrap = os.urandom(12)
        encrypted_msg_key = AESGCM(wrapping_key).encrypt(nonce_wrap, message_key, None)
        nonce_msg = os.urandom(12)
        ciphertext_msg = AESGCM(message_key).encrypt(nonce_msg, plaintext_bytes, None)

        sender_blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_msg_key": b64encode(encrypted_msg_key).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap).decode("ascii"),
            "ciphertext_msg": b64encode(ciphertext_msg).decode("ascii"),
            "nonce_msg": b64encode(nonce_msg).decode("ascii"),
        }
        return _canonical(sender_blob_dict)


class RatchetDecryptor:
    """Decrypts and verifies a version-2 ratchet message."""

    def decrypt_message(
        self,
        encrypted_msg: dict,
        *,
        peer_key: str,
        recipient_x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
        sender_x25519_pub: X25519PublicKey,
        store: RatchetSessionStore | None,
    ) -> str:
        blob_bytes = b64decode(encrypted_msg["blob"])
        signature_bytes = b64decode(encrypted_msg["signature"])

        # Verify signature before touching any ratchet state.
        sender_ed25519_pub.verify(signature_bytes, blob_bytes)

        blob = json.loads(blob_bytes.decode("utf-8"))
        if int(blob.get("v", 1)) != _VERSION:
            raise ValueError("not a ratchet (v2) blob")

        header = {"dh": blob["dh"], "pn": blob["pn"], "n": blob["n"]}
        nonce = b64decode(blob["nonce"])
        ct = b64decode(blob["ct"])
        ad = _header_ad(blob)

        my_priv_raw = recipient_x25519_priv.private_bytes_raw()
        sender_id_pub_raw = sender_x25519_pub.public_bytes_raw()
        header_dh = b64decode(header["dh"])

        existing = store.get(peer_key) if store else None

        def _try(state) -> str:
            mk = ratchet_decrypt(state, header)
            pt = AESGCM(mk).decrypt(nonce, ct, ad)  # raises InvalidTag
            return pt.decode("utf-8"), state

        if existing is None:
            plaintext, state = _try(init_bob(my_priv_raw, sender_id_pub_raw, header_dh))
            if store is not None:
                store.put(peer_key, state)
            return plaintext

        # Speculative decrypt on a copy; commit only on success. Protocol-level
        # errors (re-delivery, too-far-ahead) propagate without touching state.
        try:
            plaintext, state = _try(copy.deepcopy(existing))
        except InvalidTag:
            # Genuine key divergence: simultaneous-init race or peer lost state.
            # Heal by re-initializing as responder from the signed header.
            try:
                plaintext, state = _try(
                    init_bob(my_priv_raw, sender_id_pub_raw, header_dh)
                )
            except InvalidTag:
                # Unrecoverable: drop the broken session so our next outgoing
                # message re-establishes a fresh session with the peer.
                if store is not None:
                    store.delete(peer_key)
                raise
        if store is not None:
            store.put(peer_key, state)
        return plaintext
