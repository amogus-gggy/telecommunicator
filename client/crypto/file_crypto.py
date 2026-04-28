"""
File encryption and decryption for E2EE file transfer.

Reuses the same key-wrapping scheme as message_crypto:
  - A random 256-bit file key encrypts the file bytes (AES-256-GCM).
  - The file key is wrapped twice via ECDH(ephemeral, recipient_pub) and
    ECDH(ephemeral, sender_pub), producing two key-blobs.
  - The recipient blob is signed with the sender's Ed25519 key.
"""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from crypto.key_generator import KeyGenerator


def _derive_wrapping_key(
    shared_secret: bytes,
    ephemeral_pub_bytes: bytes,
    peer_pub_bytes: bytes,
) -> bytes:
    salt = ephemeral_pub_bytes + peer_pub_bytes
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"file-v1")
    return hkdf.derive(shared_secret)


def _wrap_file_key(
    file_key: bytes,
    ephemeral_priv: X25519PrivateKey,
    ephemeral_pub_bytes: bytes,
    peer_pub: X25519PublicKey,
) -> tuple[bytes, bytes]:
    """Return (encrypted_file_key, nonce_wrap)."""
    peer_pub_bytes = KeyGenerator.serialize_public_key(peer_pub)
    shared = ephemeral_priv.exchange(peer_pub)
    wrapping_key = _derive_wrapping_key(shared, ephemeral_pub_bytes, peer_pub_bytes)
    nonce = os.urandom(12)
    encrypted = AESGCM(wrapping_key).encrypt(nonce, file_key, None)
    return encrypted, nonce


def _unwrap_file_key(
    encrypted_file_key: bytes,
    nonce_wrap: bytes,
    ephemeral_pub_bytes: bytes,
    x25519_priv: X25519PrivateKey,
) -> bytes:
    ephemeral_pub = KeyGenerator.load_x25519_public_key(ephemeral_pub_bytes)
    shared = x25519_priv.exchange(ephemeral_pub)
    peer_pub_bytes = KeyGenerator.serialize_public_key(x25519_priv.public_key())
    wrapping_key = _derive_wrapping_key(shared, ephemeral_pub_bytes, peer_pub_bytes)
    try:
        return AESGCM(wrapping_key).decrypt(nonce_wrap, encrypted_file_key, None)
    except InvalidTag:
        raise InvalidTag("Failed to unwrap file key")


class FileEncryptor:
    """Encrypts raw file bytes for E2EE transfer."""

    def encrypt_file(
        self,
        plaintext: bytes,
        filename: str,
        recipient_x25519_pub: X25519PublicKey,
        sender_ed25519_priv: Ed25519PrivateKey,
        sender_x25519_pub: X25519PublicKey,
        sender_id: str,
        recipient_id: str,
    ) -> dict:
        """
        Encrypt file bytes.

        Returns:
            {
              "ciphertext": <bytes>,          # encrypted file content
              "key_blob": <str>,              # base64 JSON — recipient key blob
              "key_sender_blob": <str>,       # base64 JSON — sender key blob
              "signature": <str>,             # base64 Ed25519 signature over key_blob
            }
        """
        ephemeral_priv, ephemeral_pub = KeyGenerator.generate_ephemeral_keypair()
        ephemeral_pub_bytes = KeyGenerator.serialize_public_key(ephemeral_pub)

        # Encrypt file with random key
        file_key = os.urandom(32)
        nonce_file = os.urandom(12)
        ciphertext = AESGCM(file_key).encrypt(nonce_file, plaintext, None)

        # Wrap file key for recipient
        enc_key_r, nonce_wrap_r = _wrap_file_key(
            file_key, ephemeral_priv, ephemeral_pub_bytes, recipient_x25519_pub
        )
        recipient_pub_bytes = KeyGenerator.serialize_public_key(recipient_x25519_pub)

        key_blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "filename": filename,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_file_key": b64encode(enc_key_r).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap_r).decode("ascii"),
            "nonce_file": b64encode(nonce_file).decode("ascii"),
        }
        key_blob_bytes = json.dumps(
            key_blob_dict, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        # Sign recipient blob
        signature_bytes = sender_ed25519_priv.sign(key_blob_bytes)

        # Wrap file key for sender
        enc_key_s, nonce_wrap_s = _wrap_file_key(
            file_key, ephemeral_priv, ephemeral_pub_bytes, sender_x25519_pub
        )
        sender_pub_bytes = KeyGenerator.serialize_public_key(sender_x25519_pub)

        key_sender_blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "filename": filename,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_file_key": b64encode(enc_key_s).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap_s).decode("ascii"),
            "nonce_file": b64encode(nonce_file).decode("ascii"),
        }
        key_sender_blob_bytes = json.dumps(
            key_sender_blob_dict, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        return {
            "ciphertext": ciphertext,
            "key_blob": b64encode(key_blob_bytes).decode("ascii"),
            "key_sender_blob": b64encode(key_sender_blob_bytes).decode("ascii"),
            "signature": b64encode(signature_bytes).decode("ascii"),
        }


class FileDecryptor:
    """Decrypts E2EE-encrypted file bytes."""

    def decrypt_file(
        self,
        ciphertext: bytes,
        key_blob_b64: str,
        signature_b64: str,
        x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
    ) -> bytes:
        """Decrypt and verify a file received from another user."""
        key_blob_bytes = b64decode(key_blob_b64)
        signature_bytes = b64decode(signature_b64)

        try:
            sender_ed25519_pub.verify(signature_bytes, key_blob_bytes)
        except InvalidSignature:
            raise InvalidSignature("File signature verification failed")

        return self._decrypt(ciphertext, key_blob_bytes, x25519_priv)

    def decrypt_own_file(
        self,
        ciphertext: bytes,
        key_sender_blob_b64: str,
        x25519_priv: X25519PrivateKey,
    ) -> bytes:
        """Decrypt sender's own copy (no signature check)."""
        return self._decrypt(ciphertext, b64decode(key_sender_blob_b64), x25519_priv)

    @staticmethod
    def _decrypt(
        ciphertext: bytes,
        key_blob_bytes: bytes,
        x25519_priv: X25519PrivateKey,
    ) -> bytes:
        blob = json.loads(key_blob_bytes.decode("utf-8"))

        ephemeral_pub_bytes = b64decode(blob["ephemeral_pub"])
        encrypted_file_key = b64decode(blob["encrypted_file_key"])
        nonce_wrap = b64decode(blob["nonce_wrap"])
        nonce_file = b64decode(blob["nonce_file"])

        file_key = _unwrap_file_key(
            encrypted_file_key, nonce_wrap, ephemeral_pub_bytes, x25519_priv
        )

        try:
            return AESGCM(file_key).decrypt(nonce_file, ciphertext, None)
        except InvalidTag:
            raise InvalidTag("Failed to decrypt file content")
