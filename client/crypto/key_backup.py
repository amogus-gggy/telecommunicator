"""
Key backup and restore utilities for E2EE cryptographic keys.

Encrypts Ed25519 and X25519 private keys with a password using
PBKDF2-HMAC-SHA256 key derivation and AES-256-GCM encryption.

Requirements: 2.1–2.7, 3.3–3.7, 12.1–12.5
"""

import base64
import json
import os

from cryptography.exceptions import InvalidTag  # noqa: F401 – re-exported for callers
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from crypto.key_generator import KeyGenerator

PBKDF2_ITERATIONS = 600_000
_SALT_SIZE = 16
_NONCE_SIZE = 12
_KEY_SIZE = 32


class KeyBackupManager:
    """Encrypts and decrypts private key backups using password-based encryption."""

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=_KEY_SIZE,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return kdf.derive(password.encode())

    @staticmethod
    def encrypt_backup(
        ed25519_priv: Ed25519PrivateKey,
        x25519_priv: X25519PrivateKey,
        password: str,
    ) -> bytes:
        """Encrypt private keys into a portable backup blob.

        Blob format: salt(16) || nonce(12) || ciphertext+tag

        Requirements: 2.1, 2.2, 2.3, 12.1, 12.2
        """
        ed_raw = KeyGenerator.serialize_private_key(ed25519_priv)
        x_raw = KeyGenerator.serialize_private_key(x25519_priv)

        plaintext = json.dumps({
            "ed25519_priv": base64.b64encode(ed_raw).decode(),
            "x25519_priv": base64.b64encode(x_raw).decode(),
            "version": 1,
        }).encode()

        salt = os.urandom(_SALT_SIZE)
        nonce = os.urandom(_NONCE_SIZE)
        key = KeyBackupManager._derive_key(password, salt)

        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
        return salt + nonce + ciphertext

    @staticmethod
    def decrypt_backup(
        encrypted_blob: bytes,
        password: str,
    ) -> tuple[Ed25519PrivateKey, X25519PrivateKey]:
        """Decrypt a backup blob and return the private key pair.

        Raises:
            InvalidTag: if the password is wrong or the blob is corrupted.

        Requirements: 2.4, 2.5, 2.6, 2.7, 12.3, 12.4, 12.5
        """
        salt = encrypted_blob[:_SALT_SIZE]
        nonce = encrypted_blob[_SALT_SIZE:_SALT_SIZE + _NONCE_SIZE]
        ciphertext = encrypted_blob[_SALT_SIZE + _NONCE_SIZE:]

        key = KeyBackupManager._derive_key(password, salt)
        # AESGCM.decrypt raises InvalidTag on authentication failure
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)

        data = json.loads(plaintext)
        ed25519_priv = KeyGenerator.load_ed25519_private_key(
            base64.b64decode(data["ed25519_priv"])
        )
        x25519_priv = KeyGenerator.load_x25519_private_key(
            base64.b64decode(data["x25519_priv"])
        )
        return ed25519_priv, x25519_priv
