"""Tests for file encryption and decryption."""

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag

from client.crypto.key_generator import KeyGenerator
from client.crypto.file_crypto import FileEncryptor, FileDecryptor


class TestFileCrypto:

    def test_encrypt_decrypt_roundtrip(self):
        sender_ed25519_priv, sender_ed25519_pub = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = KeyGenerator.generate_prekey_keypair()

        plaintext = b"Hello, this is a secret file content!"

        enc = FileEncryptor()
        result = enc.encrypt_file(
            plaintext=plaintext,
            filename="test.txt",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        assert "ciphertext" in result
        assert result["ciphertext"] != plaintext

        dec = FileDecryptor()
        decrypted = dec.decrypt_file(
            ciphertext=result["ciphertext"],
            key_blob_b64=result["key_blob"],
            signature_b64=result["signature"],
            x25519_priv=recipient_x25519_priv,
            sender_ed25519_pub=sender_ed25519_pub,
        )
        assert decrypted == plaintext

    def test_decrypt_own_file(self):
        sender_ed25519_priv, _ = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        _, recipient_x25519_pub = KeyGenerator.generate_prekey_keypair()

        plaintext = b"Sender's own copy"

        enc = FileEncryptor()
        result = enc.encrypt_file(
            plaintext=plaintext,
            filename="own.txt",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="user1",
            recipient_id="user2",
        )

        dec = FileDecryptor()
        decrypted = dec.decrypt_own_file(
            ciphertext=result["ciphertext"],
            key_sender_blob_b64=result["key_sender_blob"],
            x25519_priv=sender_x25519_priv,
        )
        assert decrypted == plaintext

    def test_wrong_signature_fails(self):
        sender_ed25519_priv, _ = KeyGenerator.generate_identity_keypair()
        _, wrong_ed25519_pub = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = KeyGenerator.generate_prekey_keypair()

        enc = FileEncryptor()
        result = enc.encrypt_file(
            plaintext=b"secret",
            filename="f.bin",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="u1",
            recipient_id="u2",
        )

        dec = FileDecryptor()
        with pytest.raises(InvalidSignature):
            dec.decrypt_file(
                ciphertext=result["ciphertext"],
                key_blob_b64=result["key_blob"],
                signature_b64=result["signature"],
                x25519_priv=recipient_x25519_priv,
                sender_ed25519_pub=wrong_ed25519_pub,
            )

    def test_wrong_recipient_key_fails(self):
        sender_ed25519_priv, sender_ed25519_pub = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        _, recipient_x25519_pub = KeyGenerator.generate_prekey_keypair()
        wrong_x25519_priv, _ = KeyGenerator.generate_prekey_keypair()

        enc = FileEncryptor()
        result = enc.encrypt_file(
            plaintext=b"secret",
            filename="f.bin",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="u1",
            recipient_id="u2",
        )

        dec = FileDecryptor()
        with pytest.raises(InvalidTag):
            dec.decrypt_file(
                ciphertext=result["ciphertext"],
                key_blob_b64=result["key_blob"],
                signature_b64=result["signature"],
                x25519_priv=wrong_x25519_priv,
                sender_ed25519_pub=sender_ed25519_pub,
            )

    def test_binary_file(self):
        sender_ed25519_priv, sender_ed25519_pub = KeyGenerator.generate_identity_keypair()
        sender_x25519_priv, sender_x25519_pub = KeyGenerator.generate_prekey_keypair()
        recipient_x25519_priv, recipient_x25519_pub = KeyGenerator.generate_prekey_keypair()

        plaintext = bytes(range(256)) * 100  # 25.6 KB binary

        enc = FileEncryptor()
        result = enc.encrypt_file(
            plaintext=plaintext,
            filename="binary.bin",
            recipient_x25519_pub=recipient_x25519_pub,
            sender_ed25519_priv=sender_ed25519_priv,
            sender_x25519_pub=sender_x25519_pub,
            sender_id="u1",
            recipient_id="u2",
        )

        dec = FileDecryptor()
        decrypted = dec.decrypt_file(
            ciphertext=result["ciphertext"],
            key_blob_b64=result["key_blob"],
            signature_b64=result["signature"],
            x25519_priv=recipient_x25519_priv,
            sender_ed25519_pub=sender_ed25519_pub,
        )
        assert decrypted == plaintext
