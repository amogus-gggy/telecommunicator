"""Secure credentials storage for auto-login functionality."""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .settings import LocalStorage

logger = logging.getLogger(__name__)


@dataclass
class StoredCredentials:
    """Stored user credentials for auto-login."""

    server_url: str
    username: str
    password_hash: str  # Base64 encoded password (not truly secure, but better than plaintext)
    auto_login_enabled: bool = True


class CredentialsStorage:
    """Manages secure storage of user credentials for auto-login."""

    def __init__(self, storage: "LocalStorage") -> None:
        self._storage = storage

    def save_credentials(
        self, server_url: str, username: str, password: str, auto_login: bool = True
    ) -> None:
        """Save credentials for auto-login."""
        try:
            # Simple obfuscation - base64 encode (not encryption, but not plaintext)
            password_bytes = password.encode("utf-8")
            password_hash = base64.b64encode(password_bytes).decode("ascii")

            creds = StoredCredentials(
                server_url=server_url,
                username=username,
                password_hash=password_hash,
                auto_login_enabled=auto_login,
            )

            creds_dict = {
                "server_url": creds.server_url,
                "username": creds.username,
                "password_hash": creds.password_hash,
                "auto_login_enabled": creds.auto_login_enabled,
            }

            self._storage.set("credentials.stored", json.dumps(creds_dict))
            logger.info("[CredentialsStorage] Saved credentials for user: %s", username)
        except Exception as e:
            logger.error("[CredentialsStorage] Failed to save credentials: %s", e)

    def get_credentials(self) -> StoredCredentials | None:
        """Retrieve stored credentials if auto-login is enabled."""
        try:
            stored = self._storage.get("credentials.stored")
            if not stored:
                return None

            creds_dict = json.loads(stored)

            if not creds_dict.get("auto_login_enabled", False):
                return None

            return StoredCredentials(
                server_url=creds_dict["server_url"],
                username=creds_dict["username"],
                password_hash=creds_dict["password_hash"],
                auto_login_enabled=creds_dict["auto_login_enabled"],
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("[CredentialsStorage] Failed to parse stored credentials: %s", e)
            return None
        except Exception as e:
            logger.error("[CredentialsStorage] Failed to get credentials: %s", e)
            return None

    def get_password(self) -> str | None:
        """Get the stored password (decoded)."""
        creds = self.get_credentials()
        if not creds:
            return None

        try:
            password_bytes = base64.b64decode(creds.password_hash)
            return password_bytes.decode("utf-8")
        except Exception as e:
            logger.error("[CredentialsStorage] Failed to decode password: %s", e)
            return None

    def clear_credentials(self) -> None:
        """Clear stored credentials (e.g., on logout)."""
        try:
            self._storage.set("credentials.stored", "")
            logger.info("[CredentialsStorage] Cleared credentials")
        except Exception as e:
            logger.error("[CredentialsStorage] Failed to clear credentials: %s", e)

    def set_auto_login_enabled(self, enabled: bool) -> None:
        """Enable or disable auto-login without clearing credentials."""
        creds = self.get_credentials()
        if creds:
            creds.auto_login_enabled = enabled
            self.save_credentials(
                creds.server_url, creds.username, self.get_password() or "", enabled
            )

    def is_auto_login_enabled(self) -> bool:
        """Check if auto-login is enabled."""
        creds = self.get_credentials()
        return creds is not None and creds.auto_login_enabled


@dataclass
class SSHStoredCredentials:
    """Stored SSH credentials for server deployment."""

    host: str
    port: int
    username: str
    password_hash: str | None = None
    private_key_hash: str | None = None


class SSHCredentialsStorage:
    """Manages storage of SSH credentials."""

    def __init__(self, storage: "LocalStorage") -> None:
        self._storage = storage

    def save_ssh_credentials(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        private_key: str | None = None,
    ) -> None:
        """Save SSH credentials."""
        try:
            password_hash = None
            private_key_hash = None

            if password:
                password_bytes = password.encode("utf-8")
                password_hash = base64.b64encode(password_bytes).decode("ascii")

            if private_key:
                key_bytes = private_key.encode("utf-8")
                private_key_hash = base64.b64encode(key_bytes).decode("ascii")

            creds = SSHStoredCredentials(
                host=host,
                port=port,
                username=username,
                password_hash=password_hash,
                private_key_hash=private_key_hash,
            )

            creds_dict = {
                "host": creds.host,
                "port": creds.port,
                "username": creds.username,
                "password_hash": creds.password_hash,
                "private_key_hash": creds.private_key_hash,
            }

            self._storage.set("ssh.credentials", json.dumps(creds_dict))
            logger.info("[SSHCredentialsStorage] Saved SSH credentials for: %s", host)
        except Exception as e:
            logger.error("[SSHCredentialsStorage] Failed to save: %s", e)

    def get_ssh_credentials(self) -> SSHStoredCredentials | None:
        """Retrieve stored SSH credentials."""
        try:
            stored = self._storage.get("ssh.credentials")
            if not stored:
                return None

            creds_dict = json.loads(stored)
            return SSHStoredCredentials(
                host=creds_dict["host"],
                port=creds_dict.get("port", 22),
                username=creds_dict["username"],
                password_hash=creds_dict.get("password_hash"),
                private_key_hash=creds_dict.get("private_key_hash"),
            )
        except Exception as e:
            logger.warning("[SSHCredentialsStorage] Failed to load: %s", e)
            return None

    def get_password(self) -> str | None:
        """Get stored SSH password."""
        creds = self.get_ssh_credentials()
        if not creds or not creds.password_hash:
            return None
        try:
            password_bytes = base64.b64decode(creds.password_hash)
            return password_bytes.decode("utf-8")
        except Exception:
            return None

    def get_private_key(self) -> str | None:
        """Get stored SSH private key."""
        creds = self.get_ssh_credentials()
        if not creds or not creds.private_key_hash:
            return None
        try:
            key_bytes = base64.b64decode(creds.private_key_hash)
            return key_bytes.decode("utf-8")
        except Exception:
            return None

    def clear_ssh_credentials(self) -> None:
        """Clear stored SSH credentials."""
        try:
            self._storage.set("ssh.credentials", "")
            logger.info("[SSHCredentialsStorage] Cleared")
        except Exception as e:
            logger.error("[SSHCredentialsStorage] Failed to clear: %s", e)
