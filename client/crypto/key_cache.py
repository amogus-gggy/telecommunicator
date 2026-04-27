"""
Public key caching for E2EE messaging.

Provides in-memory cache for recipient public keys to avoid repeated server requests.
Requirements: 4.6, 16.1–16.3
"""

from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey


class PublicKeyCache:
    """In-memory cache for storing recipient public keys.
    
    Caches Ed25519 and X25519 public keys for users to reduce server requests.
    Cache is cleared on logout to prevent key reuse across sessions.
    
    Requirements: 4.6, 16.1–16.3
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
            
        Requirements: 4.6
        """
        return self._cache.get(user_id)

    def set_public_keys(
        self, user_id: str, ed25519_pub: Ed25519PublicKey, x25519_pub: X25519PublicKey
    ):
        """Store public keys in cache.
        
        Args:
            user_id: User identifier
            ed25519_pub: Ed25519 public key for signature verification
            x25519_pub: X25519 public key for key agreement
            
        Requirements: 4.6
        """
        self._cache[user_id] = {"ed25519_pub": ed25519_pub, "x25519_pub": x25519_pub}

    def clear(self):
        """Clear all cached keys.
        
        Called on logout to prevent key reuse across sessions.
        
        Requirements: 16.2, 16.3
        """
        self._cache.clear()
