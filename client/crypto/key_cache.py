"""
Public key caching for E2EE messaging.

Provides in-memory cache for recipient public keys to avoid repeated server requests.
"""

from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey


class PublicKeyCache:
    """In-memory cache for storing recipient public keys.

    Caches Ed25519 and X25519 public keys for users to reduce server requests.
    Cache is cleared on logout to prevent key reuse across sessions.
    """

    def __init__(self):
        """Initialize empty cache."""
        self._cache: dict[str, dict] = {}

    def get_public_keys(self, user_id: str) -> Optional[dict]:
        """Retrieve cached public keys for a user.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with 'ed25519_pub' and 'x25519_pub' keys if cached,
            None if not found

        """
        return self._cache.get(user_id)

    def set_public_keys(
        self,
        user_id: str,
        ed25519_pub: Ed25519PublicKey,
        x25519_pub: X25519PublicKey,
        numeric_user_id: str = "",
    ):
        """Store public keys in cache.

        Args:
            user_id: User identifier (username)
            ed25519_pub: Ed25519 public key for signature verification
            x25519_pub: X25519 public key for key agreement
            numeric_user_id: Numeric user ID for use as recipient_id in encryption

        """
        self._cache[user_id] = {
            "ed25519_pub": ed25519_pub,
            "x25519_pub": x25519_pub,
            "user_id": numeric_user_id,
        }

    def clear(self):
        """Clear all cached keys.

        Called on logout to prevent key reuse across sessions.

        """
        self._cache.clear()
