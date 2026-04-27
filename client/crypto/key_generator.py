"""
Key generation and serialization utilities for E2EE cryptographic operations.

Supports Ed25519 (identity/signing) and X25519 (key agreement) key pairs.

"""

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from state import AppState


class KeyGenerator:
    """Generates and serializes cryptographic key pairs for E2EE messaging."""

    @staticmethod
    def generate_identity_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
        """Generate an Ed25519 signing key pair for user identity.

        """
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key

    @staticmethod
    def generate_prekey_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
        """Generate an X25519 key agreement pair for encryption (prekey).

        """
        private_key = X25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key

    @staticmethod
    def generate_ephemeral_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
        """Generate an ephemeral X25519 key pair for a single message.

        Requirements: 5.1, 10.2, 10.5
        """
        private_key = X25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key

    @staticmethod
    def serialize_public_key(pub: Ed25519PublicKey | X25519PublicKey) -> bytes:
        """Serialize a public key to raw bytes (32 bytes).

        """
        return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)

    @staticmethod
    def serialize_private_key(priv: Ed25519PrivateKey | X25519PrivateKey) -> bytes:
        """Serialize a private key to raw bytes (32 bytes), no encryption.

        """
        return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    @staticmethod
    def load_ed25519_public_key(raw: bytes) -> Ed25519PublicKey:
        """Load an Ed25519 public key from raw bytes."""
        return Ed25519PublicKey.from_public_bytes(raw)

    @staticmethod
    def load_x25519_public_key(raw: bytes) -> X25519PublicKey:
        """Load an X25519 public key from raw bytes."""
        return X25519PublicKey.from_public_bytes(raw)

    @staticmethod
    def load_ed25519_private_key(raw: bytes) -> Ed25519PrivateKey:
        """Load an Ed25519 private key from raw bytes."""
        return Ed25519PrivateKey.from_private_bytes(raw)

    @staticmethod
    def load_x25519_private_key(raw: bytes) -> X25519PrivateKey:
        """Load an X25519 private key from raw bytes."""
        return X25519PrivateKey.from_private_bytes(raw)

    @staticmethod
    def rotate_prekey(state: "AppState") -> tuple[X25519PrivateKey, X25519PublicKey]:
        """Generate a new X25519 prekey pair and store old key for grace period.
        
        Args:
            state: AppState instance to update with new keys
            
        Returns:
            Tuple of (new_private_key, new_public_key)
        """
        
        # Store old private key for grace period
        if state.x25519_private:
            state.old_x25519_private = state.x25519_private
        
        # Generate new keypair
        new_private, new_public = KeyGenerator.generate_prekey_keypair()
        
        # Update state with new key
        state.x25519_private = new_private
        
        return new_private, new_public
