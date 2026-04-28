"""
Tests for message encryption and decryption.

Validates MessageEncryptor and MessageDecryptor functionality.
"""

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag

from client.crypto.key_generator import KeyGenerator
from client.crypto.message_crypto import MessageDecryptor, MessageEncryptor


class TestMessageCrypto:
    """Test message encryption and decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption work correctly."""
        # Generate keys for sender and recipient
        sender_ed25519_priv, sender_ed25519_pub = (
            KeyGenerator.generate_identity_keypair()
        )
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = (
            KeyGenerator.generate_prekey_keypair()
        )

        # Create encryptor and decryptor
        encryptor = MessageEncryptor()
        decryptor = MessageDecryptor()

        # Test message
        plaintext = "Hello, this is a secret message!"
        sender_id = "user123"
        recipient_id = "user456"

        # Encrypt
        encrypted_msg = encryptor.encrypt_message(
            plaintext=plaintext,
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id=sender_id,
            recipient_id=recipient_id,
        )

        # Verify structure
        assert "blob" in encrypted_msg
        assert "signature" in encrypted_msg

        # Decrypt
        decrypted_plaintext = decryptor.decrypt_message(
            encrypted_msg=encrypted_msg,
            recipient_x25519_priv=recipient_x25519_priv,
            sender_ed25519_pub=sender_ed25519_pub,
        )

        # Verify plaintext matches
        assert decrypted_plaintext == plaintext

    def test_decrypt_with_wrong_signature_fails(self):
        """Test that decryption fails with wrong sender public key."""
        # Generate keys
        sender_ed25519_priv, _ = KeyGenerator.generate_identity_keypair()
        _, wrong_ed25519_pub = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = (
            KeyGenerator.generate_prekey_keypair()
        )

        encryptor = MessageEncryptor()
        decryptor = MessageDecryptor()

        # Encrypt message
        encrypted_msg = encryptor.encrypt_message(
            plaintext="Secret message",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        # Try to decrypt with wrong sender public key
        with pytest.raises(InvalidSignature):
            decryptor.decrypt_message(
                encrypted_msg=encrypted_msg,
                recipient_x25519_priv=recipient_x25519_priv,
                sender_ed25519_pub=wrong_ed25519_pub,
            )

    def test_decrypt_with_wrong_recipient_key_fails(self):
        """Test that decryption fails with wrong recipient private key."""
        # Generate keys
        sender_ed25519_priv, sender_ed25519_pub = (
            KeyGenerator.generate_identity_keypair()
        )
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = (
            KeyGenerator.generate_prekey_keypair()
        )
        wrong_x25519_priv, _ = KeyGenerator.generate_prekey_keypair()

        encryptor = MessageEncryptor()
        decryptor = MessageDecryptor()

        # Encrypt message
        encrypted_msg = encryptor.encrypt_message(
            plaintext="Secret message",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        # Try to decrypt with wrong recipient private key
        with pytest.raises(InvalidTag):
            decryptor.decrypt_message(
                encrypted_msg=encrypted_msg,
                recipient_x25519_priv=wrong_x25519_priv,
                sender_ed25519_pub=sender_ed25519_pub,
            )

    def test_encrypt_empty_message(self):
        """Test encryption of empty message."""
        sender_ed25519_priv, sender_ed25519_pub = (
            KeyGenerator.generate_identity_keypair()
        )
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = (
            KeyGenerator.generate_prekey_keypair()
        )

        encryptor = MessageEncryptor()
        decryptor = MessageDecryptor()

        plaintext = ""

        encrypted_msg = encryptor.encrypt_message(
            plaintext=plaintext,
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        decrypted_plaintext = decryptor.decrypt_message(
            encrypted_msg=encrypted_msg,
            recipient_x25519_priv=recipient_x25519_priv,
            sender_ed25519_pub=sender_ed25519_pub,
        )

        assert decrypted_plaintext == plaintext

    def test_encrypt_unicode_message(self):
        """Test encryption of Unicode message."""
        sender_ed25519_priv, sender_ed25519_pub = (
            KeyGenerator.generate_identity_keypair()
        )
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = (
            KeyGenerator.generate_prekey_keypair()
        )

        encryptor = MessageEncryptor()
        decryptor = MessageDecryptor()

        plaintext = "Hello 世界! 🔒🔐"

        encrypted_msg = encryptor.encrypt_message(
            plaintext=plaintext,
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        decrypted_plaintext = decryptor.decrypt_message(
            encrypted_msg=encrypted_msg,
            recipient_x25519_priv=recipient_x25519_priv,
            sender_ed25519_pub=sender_ed25519_pub,
        )

        assert decrypted_plaintext == plaintext
