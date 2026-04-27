"""
Message encryption and decryption for E2EE messaging.

Implements forward-secret message encryption using ephemeral X25519 keys,
ECDH key agreement, HKDF key derivation, and AES-256-GCM authenticated encryption.
"""

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


class MessageEncryptor:
    """Encrypts messages with forward secrecy using ephemeral keys."""

    def encrypt_message(
        self,
        plaintext: str,
        recipient_x25519_pub: X25519PublicKey,
        sender_ed25519_priv: Ed25519PrivateKey,
        sender_x25519_pub: X25519PublicKey,
        sender_id: str,
        recipient_id: str,
    ) -> dict:
        """
        Encrypt a message for both recipient and sender (double encryption).

        The message key is generated once and encrypted twice:
        - once with a wrapping key derived from ECDH(ephemeral, recipient_pub)  → blob for recipient
        - once with a wrapping key derived from ECDH(ephemeral, sender_pub)     → blob for sender

        Both blobs share the same ciphertext and signature, so E2EE is preserved.

        Returns:
            dict with "blob", "sender_blob", "signature" (all base64 encoded)
        """
        # 1. Generate ephemeral X25519 keypair
        ephemeral_priv, ephemeral_pub = KeyGenerator.generate_ephemeral_keypair()
        ephemeral_pub_bytes = KeyGenerator.serialize_public_key(ephemeral_pub)

        # 2. Encrypt plaintext with a random message key (shared between both copies)
        message_key = os.urandom(32)
        nonce_msg = os.urandom(12)
        aesgcm_msg = AESGCM(message_key)
        ciphertext_msg = aesgcm_msg.encrypt(nonce_msg, plaintext.encode("utf-8"), None)

        # 3. Build recipient blob — message key wrapped with ECDH(ephemeral, recipient_pub)
        recipient_pub_bytes = KeyGenerator.serialize_public_key(recipient_x25519_pub)
        shared_secret_r = ephemeral_priv.exchange(recipient_x25519_pub)
        wrapping_key_r = self._derive_wrapping_key(shared_secret_r, ephemeral_pub_bytes, recipient_pub_bytes)
        nonce_wrap_r = os.urandom(12)
        encrypted_msg_key_r = AESGCM(wrapping_key_r).encrypt(nonce_wrap_r, message_key, None)

        blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_msg_key": b64encode(encrypted_msg_key_r).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap_r).decode("ascii"),
            "ciphertext_msg": b64encode(ciphertext_msg).decode("ascii"),
            "nonce_msg": b64encode(nonce_msg).decode("ascii"),
        }
        json_bytes = json.dumps(blob_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")

        # 4. Sign the recipient blob
        signature_bytes = sender_ed25519_priv.sign(json_bytes)

        # 5. Build sender blob — same ciphertext, message key wrapped with ECDH(ephemeral, sender_pub)
        sender_pub_bytes = KeyGenerator.serialize_public_key(sender_x25519_pub)
        shared_secret_s = ephemeral_priv.exchange(sender_x25519_pub)
        wrapping_key_s = self._derive_wrapping_key(shared_secret_s, ephemeral_pub_bytes, sender_pub_bytes)
        nonce_wrap_s = os.urandom(12)
        encrypted_msg_key_s = AESGCM(wrapping_key_s).encrypt(nonce_wrap_s, message_key, None)

        sender_blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_msg_key": b64encode(encrypted_msg_key_s).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap_s).decode("ascii"),
            "ciphertext_msg": b64encode(ciphertext_msg).decode("ascii"),
            "nonce_msg": b64encode(nonce_msg).decode("ascii"),
        }
        sender_json_bytes = json.dumps(sender_blob_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")

        return {
            "blob": b64encode(json_bytes).decode("ascii"),
            "sender_blob": b64encode(sender_json_bytes).decode("ascii"),
            "signature": b64encode(signature_bytes).decode("ascii"),
        }

    @staticmethod
    def _derive_wrapping_key(shared_secret: bytes, ephemeral_pub_bytes: bytes, peer_pub_bytes: bytes) -> bytes:
        salt = ephemeral_pub_bytes + peer_pub_bytes
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"msg-v1")
        return hkdf.derive(shared_secret)


class MessageDecryptor:
    """Decrypts and verifies encrypted messages."""

    def decrypt_message(
        self,
        encrypted_msg: dict,
        recipient_x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
    ) -> str:
        """Decrypt and verify a message received from another user."""
        blob_bytes = b64decode(encrypted_msg["blob"])
        signature_bytes = b64decode(encrypted_msg["signature"])

        try:
            sender_ed25519_pub.verify(signature_bytes, blob_bytes)
        except InvalidSignature:
            raise InvalidSignature("Message signature verification failed")

        return self._decrypt_blob(blob_bytes, recipient_x25519_priv)

    def decrypt_own_message(
        self,
        sender_blob_b64: str,
        sender_x25519_priv: X25519PrivateKey,
    ) -> str:
        """Decrypt the sender's own copy of a sent message (no signature check needed)."""
        return self._decrypt_blob(b64decode(sender_blob_b64), sender_x25519_priv)

    @staticmethod
    def _decrypt_blob(blob_bytes: bytes, x25519_priv: X25519PrivateKey) -> str:
        blob_dict = json.loads(blob_bytes.decode("utf-8"))

        ephemeral_pub_bytes = b64decode(blob_dict["ephemeral_pub"])
        encrypted_msg_key = b64decode(blob_dict["encrypted_msg_key"])
        nonce_wrap = b64decode(blob_dict["nonce_wrap"])
        ciphertext_msg = b64decode(blob_dict["ciphertext_msg"])
        nonce_msg = b64decode(blob_dict["nonce_msg"])

        ephemeral_pub = KeyGenerator.load_x25519_public_key(ephemeral_pub_bytes)
        shared_secret = x25519_priv.exchange(ephemeral_pub)

        peer_pub_bytes = KeyGenerator.serialize_public_key(x25519_priv.public_key())
        salt = ephemeral_pub_bytes + peer_pub_bytes
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"msg-v1")
        wrapping_key = hkdf.derive(shared_secret)

        try:
            message_key = AESGCM(wrapping_key).decrypt(nonce_wrap, encrypted_msg_key, None)
        except InvalidTag:
            raise InvalidTag("Failed to decrypt message key")

        try:
            plaintext_bytes = AESGCM(message_key).decrypt(nonce_msg, ciphertext_msg, None)
        except InvalidTag:
            raise InvalidTag("Failed to decrypt message plaintext")

        return plaintext_bytes.decode("utf-8")
