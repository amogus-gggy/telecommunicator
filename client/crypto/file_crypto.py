"""
Streaming file encryption/decryption for E2EE file transfer.

Scheme
------
* A random 256-bit *file key* is generated per upload.
* The file is encrypted in 1 MiB chunks, each with its own random 12-byte
  nonce, using AES-256-GCM.  The chunk index is included as AAD so chunks
  cannot be reordered.
* Wire format (concatenated):
      [8 bytes: total chunk count, big-endian uint64]
      for each chunk:
          [4 bytes: ciphertext length, big-endian uint32]
          [12 bytes: nonce]
          [N bytes: ciphertext + 16-byte GCM tag]
* The file key is wrapped (ECDH + HKDF + AES-GCM) for both recipient and
  sender, exactly as before — only the file body format changes.
* Key blobs are identical in structure to the previous version so the server
  schema is unchanged.
"""

from __future__ import annotations

import io
import json
import os
import struct
from base64 import b64decode, b64encode
from typing import BinaryIO, Iterator

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

CHUNK_SIZE = 1 * 1024 * 1024  # 1 MiB plaintext per chunk


# ---------------------------------------------------------------------------
# Key wrapping helpers (unchanged from previous version)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Streaming encrypt
# ---------------------------------------------------------------------------

def encrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    file_key: bytes,
) -> int:
    """Encrypt *src* into *dst* using chunked AES-256-GCM.

    Returns the number of plaintext bytes processed.
    The chunk count header is written first (8 bytes, big-endian uint64).
    Each chunk: 4-byte length | 12-byte nonce | ciphertext+tag.
    """
    aesgcm = AESGCM(file_key)

    # We don't know chunk count upfront — write placeholder, seek back later
    count_offset = dst.tell()
    dst.write(b"\x00" * 8)

    chunk_index = 0
    total_plain = 0

    while True:
        plain = src.read(CHUNK_SIZE)
        if not plain:
            break
        total_plain += len(plain)
        nonce = os.urandom(12)
        aad = struct.pack(">Q", chunk_index)  # chunk index as AAD
        ct = aesgcm.encrypt(nonce, plain, aad)
        dst.write(struct.pack(">I", len(ct)))
        dst.write(nonce)
        dst.write(ct)
        chunk_index += 1

    # Patch chunk count
    end_offset = dst.tell()
    dst.seek(count_offset)
    dst.write(struct.pack(">Q", chunk_index))
    dst.seek(end_offset)

    return total_plain


def decrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    file_key: bytes,
) -> int:
    """Decrypt *src* into *dst*.  Returns plaintext bytes written."""
    aesgcm = AESGCM(file_key)

    header = src.read(8)
    if len(header) < 8:
        raise ValueError("Truncated file: missing chunk count header")
    total_chunks = struct.unpack(">Q", header)[0]

    total_plain = 0
    for chunk_index in range(total_chunks):
        len_buf = src.read(4)
        if len(len_buf) < 4:
            raise ValueError(f"Truncated file at chunk {chunk_index}")
        ct_len = struct.unpack(">I", len_buf)[0]
        nonce = src.read(12)
        ct = src.read(ct_len)
        if len(nonce) < 12 or len(ct) < ct_len:
            raise ValueError(f"Truncated chunk {chunk_index}")
        aad = struct.pack(">Q", chunk_index)
        plain = aesgcm.decrypt(nonce, ct, aad)
        dst.write(plain)
        total_plain += len(plain)

    return total_plain


# ---------------------------------------------------------------------------
# Key-blob helpers
# ---------------------------------------------------------------------------

def _make_key_blob(
    file_key: bytes,
    ephemeral_priv: X25519PrivateKey,
    ephemeral_pub_bytes: bytes,
    peer_pub: X25519PublicKey,
    sender_id: str,
    recipient_id: str,
    filename: str,
) -> tuple[str, str]:
    """Return (key_blob_b64, nonce_wrap_b64) — does NOT include nonce_file."""
    enc_key, nonce_wrap = _wrap_file_key(
        file_key, ephemeral_priv, ephemeral_pub_bytes, peer_pub
    )
    blob_dict = {
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "filename": filename,
        "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
        "encrypted_file_key": b64encode(enc_key).decode("ascii"),
        "nonce_wrap": b64encode(nonce_wrap).decode("ascii"),
        # nonce_file removed — nonces are now per-chunk inside the stream
        "version": 2,
    }
    blob_bytes = json.dumps(blob_dict, sort_keys=True, separators=(",", ":")).encode()
    return b64encode(blob_bytes).decode("ascii"), blob_bytes


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

class FileEncryptor:
    """Encrypts a file stream for E2EE transfer."""

    def encrypt_file_streaming(
        self,
        src_path: str,
        dst: BinaryIO,
        filename: str,
        recipient_x25519_pub: X25519PublicKey,
        sender_ed25519_priv: Ed25519PrivateKey,
        sender_x25519_pub: X25519PublicKey,
        sender_id: str,
        recipient_id: str,
    ) -> dict:
        """Stream-encrypt *src_path* into *dst*.

        Returns key metadata dict (no ciphertext — it's already written to dst).
        """
        ephemeral_priv, ephemeral_pub = KeyGenerator.generate_ephemeral_keypair()
        ephemeral_pub_bytes = KeyGenerator.serialize_public_key(ephemeral_pub)
        file_key = os.urandom(32)

        with open(src_path, "rb") as src:
            encrypt_stream(src, dst, file_key)

        key_blob_b64, key_blob_bytes = _make_key_blob(
            file_key, ephemeral_priv, ephemeral_pub_bytes,
            recipient_x25519_pub, sender_id, recipient_id, filename,
        )
        signature_bytes = sender_ed25519_priv.sign(key_blob_bytes)

        key_sender_blob_b64, _ = _make_key_blob(
            file_key, ephemeral_priv, ephemeral_pub_bytes,
            sender_x25519_pub, sender_id, recipient_id, filename,
        )

        return {
            "key_blob": key_blob_b64,
            "key_sender_blob": key_sender_blob_b64,
            "signature": b64encode(signature_bytes).decode("ascii"),
        }

    # Keep old in-memory API for backwards compat (small files / tests)
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
        buf = io.BytesIO()
        src = io.BytesIO(plaintext)
        ephemeral_priv, ephemeral_pub = KeyGenerator.generate_ephemeral_keypair()
        ephemeral_pub_bytes = KeyGenerator.serialize_public_key(ephemeral_pub)
        file_key = os.urandom(32)
        encrypt_stream(src, buf, file_key)

        key_blob_b64, key_blob_bytes = _make_key_blob(
            file_key, ephemeral_priv, ephemeral_pub_bytes,
            recipient_x25519_pub, sender_id, recipient_id, filename,
        )
        signature_bytes = sender_ed25519_priv.sign(key_blob_bytes)
        key_sender_blob_b64, _ = _make_key_blob(
            file_key, ephemeral_priv, ephemeral_pub_bytes,
            sender_x25519_pub, sender_id, recipient_id, filename,
        )
        return {
            "ciphertext": buf.getvalue(),
            "key_blob": key_blob_b64,
            "key_sender_blob": key_sender_blob_b64,
            "signature": b64encode(signature_bytes).decode("ascii"),
        }


class FileDecryptor:
    """Decrypts E2EE-encrypted file streams."""

    def decrypt_file_streaming(
        self,
        src: BinaryIO,
        dst: BinaryIO,
        key_blob_b64: str,
        signature_b64: str,
        x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
    ) -> None:
        key_blob_bytes = b64decode(key_blob_b64)
        try:
            sender_ed25519_pub.verify(b64decode(signature_b64), key_blob_bytes)
        except InvalidSignature:
            raise InvalidSignature("File signature verification failed")
        file_key = self._unwrap_key(key_blob_bytes, x25519_priv)
        decrypt_stream(src, dst, file_key)

    def decrypt_own_file_streaming(
        self,
        src: BinaryIO,
        dst: BinaryIO,
        key_sender_blob_b64: str,
        x25519_priv: X25519PrivateKey,
    ) -> None:
        file_key = self._unwrap_key(b64decode(key_sender_blob_b64), x25519_priv)
        decrypt_stream(src, dst, file_key)

    @staticmethod
    def _unwrap_key(key_blob_bytes: bytes, x25519_priv: X25519PrivateKey) -> bytes:
        blob = json.loads(key_blob_bytes.decode("utf-8"))
        return _unwrap_file_key(
            b64decode(blob["encrypted_file_key"]),
            b64decode(blob["nonce_wrap"]),
            b64decode(blob["ephemeral_pub"]),
            x25519_priv,
        )

    # Legacy in-memory API (v1 blobs that have nonce_file)
    def decrypt_file(
        self,
        ciphertext: bytes,
        key_blob_b64: str,
        signature_b64: str,
        x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
    ) -> bytes:
        key_blob_bytes = b64decode(key_blob_b64)
        try:
            sender_ed25519_pub.verify(b64decode(signature_b64), key_blob_bytes)
        except InvalidSignature:
            raise InvalidSignature("File signature verification failed")
        return self._decrypt_legacy(ciphertext, key_blob_bytes, x25519_priv)

    def decrypt_own_file(
        self,
        ciphertext: bytes,
        key_sender_blob_b64: str,
        x25519_priv: X25519PrivateKey,
    ) -> bytes:
        return self._decrypt_legacy(
            ciphertext, b64decode(key_sender_blob_b64), x25519_priv
        )

    @staticmethod
    def _decrypt_legacy(
        ciphertext: bytes,
        key_blob_bytes: bytes,
        x25519_priv: X25519PrivateKey,
    ) -> bytes:
        blob = json.loads(key_blob_bytes.decode("utf-8"))
        file_key = _unwrap_file_key(
            b64decode(blob["encrypted_file_key"]),
            b64decode(blob["nonce_wrap"]),
            b64decode(blob["ephemeral_pub"]),
            x25519_priv,
        )
        # v1: single GCM block
        if "nonce_file" in blob:
            nonce_file = b64decode(blob["nonce_file"])
            try:
                return AESGCM(file_key).decrypt(nonce_file, ciphertext, None)
            except InvalidTag:
                raise InvalidTag("Failed to decrypt file content")
        # v2: chunked stream
        src = io.BytesIO(ciphertext)
        dst = io.BytesIO()
        decrypt_stream(src, dst, file_key)
        return dst.getvalue()
