"""
Message encryption and decryption for E2EE messaging.

Implements forward-secret message encryption using ephemeral X25519 keys,
ECDH key agreement, HKDF key derivation, and AES-256-GCM authenticated encryption.
Requirements: 5.1–5.8, 6.1–6.6, 7.1–7.6, 11.1–11.4, 13.1–13.5
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

from client.crypto.key_generator import KeyGenerator


class MessageEncryptor:
    """Encrypts messages with forward secrecy using ephemeral keys."""

    def encrypt_message(
        self,
        plaintext: str,
        recipient_x25519_pub: X25519PublicKey,
        sender_ed25519_priv: Ed25519PrivateKey,
        sender_id: str,
        recipient_id: str,
    ) -> dict:
        """
        Encrypt a message with forward secrecy and sign it.

        Args:
            plaintext: Message text to encrypt
            recipient_x25519_pub: Recipient's X25519 public key
            sender_ed25519_priv: Sender's Ed25519 private key for signing
            sender_id: Sender's user ID
            recipient_id: Recipient's user ID

        Returns:
            dict with "blob" (base64 encoded JSON) and "signature" (base64 encoded)

        Requirements: 5.1–5.8, 6.1–6.6, 7.1–7.6
        """
        # 1. Generate ephemeral X25519 keypair
        ephemeral_priv, ephemeral_pub = KeyGenerator.generate_ephemeral_keypair()

        # 2. ECDH: shared_secret = ephemeral_priv.exchange(recipient_pub)
        shared_secret = ephemeral_priv.exchange(recipient_x25519_pub)

        # 3. Derive wrapping key with HKDF-SHA256
        ephemeral_pub_bytes = KeyGenerator.serialize_public_key(ephemeral_pub)
        recipient_pub_bytes = KeyGenerator.serialize_public_key(recipient_x25519_pub)
        salt = ephemeral_pub_bytes + recipient_pub_bytes

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"msg-v1",
        )
        wrapping_key = hkdf.derive(shared_secret)

        # 4. Generate random 32-byte message key
        message_key = os.urandom(32)

        # 5. Encrypt message key with wrapping key (AES-256-GCM, 12-byte nonce)
        nonce_wrap = os.urandom(12)
        aesgcm_wrap = AESGCM(wrapping_key)
        encrypted_msg_key = aesgcm_wrap.encrypt(nonce_wrap, message_key, None)

        # 6. Encrypt plaintext with message key (AES-256-GCM, 12-byte nonce)
        nonce_msg = os.urandom(12)
        aesgcm_msg = AESGCM(message_key)
        plaintext_bytes = plaintext.encode("utf-8")
        ciphertext_msg = aesgcm_msg.encrypt(nonce_msg, plaintext_bytes, None)

        # 7. Build canonical JSON structure
        blob_dict = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "ephemeral_pub": b64encode(ephemeral_pub_bytes).decode("ascii"),
            "encrypted_msg_key": b64encode(encrypted_msg_key).decode("ascii"),
            "nonce_wrap": b64encode(nonce_wrap).decode("ascii"),
            "ciphertext_msg": b64encode(ciphertext_msg).decode("ascii"),
            "nonce_msg": b64encode(nonce_msg).decode("ascii"),
        }

        # Canonical JSON: sorted keys, no whitespace
        json_bytes = json.dumps(blob_dict, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

        # 8. Sign the JSON bytes with sender's Ed25519 private key
        signature_bytes = sender_ed25519_priv.sign(json_bytes)

        # 9. Return {"blob": base64(json_bytes), "signature": base64(signature_bytes)}
        return {
            "blob": b64encode(json_bytes).decode("ascii"),
            "signature": b64encode(signature_bytes).decode("ascii"),
        }


class MessageDecryptor:
    """Decrypts and verifies encrypted messages."""

    def decrypt_message(
        self,
        encrypted_msg: dict,
        recipient_x25519_priv: X25519PrivateKey,
        sender_ed25519_pub: Ed25519PublicKey,
    ) -> str:
        """
        Decrypt and verify a message.

        Args:
            encrypted_msg: dict with "blob" and "signature" (both base64 encoded)
            recipient_x25519_priv: Recipient's X25519 private key
            sender_ed25519_pub: Sender's Ed25519 public key for verification

        Returns:
            Decrypted plaintext string

        Raises:
            InvalidSignature: If signature verification fails
            InvalidTag: If decryption fails (wrong key or tampered ciphertext)

        Requirements: 5.1–5.8, 6.1–6.6, 7.1–7.6, 11.1–11.4, 13.1–13.5
        """
        # 1. Parse encrypted_msg dict, base64-decode blob and signature
        blob_bytes = b64decode(encrypted_msg["blob"])
        signature_bytes = b64decode(encrypted_msg["signature"])

        # 2. Verify Ed25519 signature on blob using sender's public key
        try:
            sender_ed25519_pub.verify(signature_bytes, blob_bytes)
        except InvalidSignature:
            raise InvalidSignature("Message signature verification failed")

        # 3. Parse JSON blob to extract components
        blob_dict = json.loads(blob_bytes.decode("utf-8"))

        ephemeral_pub_bytes = b64decode(blob_dict["ephemeral_pub"])
        encrypted_msg_key = b64decode(blob_dict["encrypted_msg_key"])
        nonce_wrap = b64decode(blob_dict["nonce_wrap"])
        ciphertext_msg = b64decode(blob_dict["ciphertext_msg"])
        nonce_msg = b64decode(blob_dict["nonce_msg"])

        # 4. ECDH: shared_secret = recipient_priv.exchange(ephemeral_pub)
        ephemeral_pub = KeyGenerator.load_x25519_public_key(ephemeral_pub_bytes)
        shared_secret = recipient_x25519_priv.exchange(ephemeral_pub)

        # 5. Derive wrapping key with same HKDF parameters
        recipient_pub_bytes = KeyGenerator.serialize_public_key(
            recipient_x25519_priv.public_key()
        )
        salt = ephemeral_pub_bytes + recipient_pub_bytes

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"msg-v1",
        )
        wrapping_key = hkdf.derive(shared_secret)

        # 6. Decrypt message key (raise InvalidTag if fails)
        aesgcm_wrap = AESGCM(wrapping_key)
        try:
            message_key = aesgcm_wrap.decrypt(nonce_wrap, encrypted_msg_key, None)
        except InvalidTag:
            raise InvalidTag("Failed to decrypt message key")

        # 7. Decrypt plaintext with message key (raise InvalidTag if fails)
        aesgcm_msg = AESGCM(message_key)
        try:
            plaintext_bytes = aesgcm_msg.decrypt(nonce_msg, ciphertext_msg, None)
        except InvalidTag:
            raise InvalidTag("Failed to decrypt message plaintext")

        # 8. Return plaintext string
        return plaintext_bytes.decode("utf-8")
