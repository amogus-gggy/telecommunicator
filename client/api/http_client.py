from __future__ import annotations

from typing import Any

import httpx

from config import API_URL
from state import AppState


class APIError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthError(APIError):
    """Raised on 401 — session expired or invalid credentials."""
    def __init__(self, message: str) -> None:
        super().__init__(message, 401)


class ForbiddenError(APIError):
    """Raised on 403."""
    def __init__(self, message: str) -> None:
        super().__init__(message, 403)


class ConflictError(APIError):
    """Raised on 409."""
    def __init__(self, message: str) -> None:
        super().__init__(message, 409)


class ValidationError(APIError):
    """Raised on 422."""
    def __init__(self, message: str) -> None:
        super().__init__(message, 422)


def _parse_detail(response: httpx.Response) -> str:
    """Extract the `detail` field from a JSON error body, falling back to raw text."""
    try:
        body = response.json()
        detail = body.get("detail", "")
        if isinstance(detail, list):
            return "; ".join(
                e.get("msg", str(e)) for e in detail if isinstance(e, dict)
            )
        return str(detail) if detail else response.text
    except Exception:
        return response.text


def _raise_for_status(response: httpx.Response) -> None:
    """Raise a typed exception for 4xx/5xx responses."""
    if response.status_code == 401:
        raise AuthError(_parse_detail(response))
    if response.status_code == 403:
        raise ForbiddenError(_parse_detail(response))
    if response.status_code == 409:
        raise ConflictError(_parse_detail(response))
    if response.status_code == 422:
        raise ValidationError(_parse_detail(response))
    if response.is_error:
        raise APIError(_parse_detail(response), response.status_code)


class APIClient:
    """Thin async wrapper around httpx.AsyncClient for the messenger REST API."""

    def __init__(self, base_url: str | None = None, state: AppState | None = None) -> None:
        self.base_url = (base_url or API_URL).rstrip("/")
        self.state = state or AppState()
        self._client = httpx.AsyncClient(base_url=self.base_url)

    def _headers(self) -> dict[str, str]:
        if self.state.token:
            return {"Authorization": f"Bearer {self.state.token}"}
        return {}

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.get(path, headers=self._headers(), **kwargs)
        _raise_for_status(response)
        return response

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.post(path, headers=self._headers(), **kwargs)
        _raise_for_status(response)
        return response

    async def _patch(self, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.patch(path, headers=self._headers(), **kwargs)
        _raise_for_status(response)
        return response

    async def _delete(self, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.delete(path, headers=self._headers(), **kwargs)
        _raise_for_status(response)
        return response

    # Auth
    async def register(self, username: str, email: str, password: str, identity_pub_ed25519: str, identity_pub_x25519: str, encrypted_backup: str) -> dict:
        r = await self._post("/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
            "identity_pub_ed25519": identity_pub_ed25519,
            "identity_pub_x25519": identity_pub_x25519,
            "encrypted_backup": encrypted_backup
        })
        return r.json()

    async def login(self, username: str, password: str) -> dict:
        r = await self._post("/auth/login", json={"username": username, "password": password})
        return r.json()

    async def logout(self) -> None:
        self.state.token = None
        self.state.current_user = None
        self.state.active_room = None
        self.state.clear_crypto_keys()

    # Users
    async def get_me(self) -> dict:
        r = await self._get("/users/me")
        return r.json()

    async def get_my_rooms(self) -> list[dict]:
        r = await self._get("/users/me/rooms")
        return r.json()

    async def get_user(self, username: str) -> dict:
        r = await self._get(f"/users/{username}")
        return r.json()

    async def update_profile(self, display_name: str) -> dict:
        r = await self._patch("/users/me", json={"display_name": display_name})
        return r.json()

    async def change_password(self, current_password: str, new_password: str) -> None:
        await self._post("/users/me/password", json={"current_password": current_password, "new_password": new_password})

    # Rooms
    async def list_rooms(self) -> list[dict]:
        r = await self._get("/rooms")
        return r.json()

    async def create_room(self, name: str, room_type: str = "public", is_private: bool = False) -> dict:
        r = await self._post("/rooms", json={"name": name, "room_type": room_type, "is_private": is_private})
        return r.json()

    async def create_personal_chat(self, username: str) -> dict:
        r = await self._post("/rooms/personal", json={"username": username})
        return r.json()

    async def join_room(self, room_id: int) -> None:
        await self._post(f"/rooms/{room_id}/join")

    async def leave_room(self, room_id: int) -> None:
        await self._post(f"/rooms/{room_id}/leave")

    async def invite_user(self, room_id: int, username: str) -> None:
        await self._post(f"/rooms/{room_id}/invite/{username}")

    async def remove_member(self, room_id: int, username: str) -> None:
        await self._delete(f"/rooms/{room_id}/members/{username}")

    async def update_permissions(self, room_id: int, allow_member_invite: bool | None = None, read_only: bool | None = None) -> dict:
        payload: dict[str, Any] = {}
        if allow_member_invite is not None:
            payload["allow_member_invite"] = allow_member_invite
        if read_only is not None:
            payload["read_only"] = read_only
        r = await self._patch(f"/rooms/{room_id}/permissions", json=payload)
        return r.json()

    # Messages
    async def get_messages(self, room_id: int, before_id: int | None = None, limit: int = 50) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if before_id is not None:
            params["before_id"] = before_id
        r = await self._get(f"/rooms/{room_id}/messages", params=params)
        return r.json()

    # E2EE endpoints
    async def get_public_keys(self, username: str) -> dict:
        r = await self._get(f"/users/{username}/public-keys")
        return r.json()

    async def update_public_keys(self, ed25519_pub_b64: str, x25519_pub_b64: str) -> dict:
        r = await self._put("/users/me/public-keys", json={
            "identity_pub_ed25519": ed25519_pub_b64,
            "identity_pub_x25519": x25519_pub_b64
        })
        return r.json()

    async def get_backup(self) -> dict:
        r = await self._get("/backup")
        return r.json()

    async def update_backup(self, encrypted_backup_b64: str) -> dict:
        r = await self._put("/backup", json={"encrypted_backup": encrypted_backup_b64})
        return r.json()

    async def send_encrypted_message(self, room_id: int, recipient_username: str, encrypted_blob_b64: str, sender_encrypted_blob_b64: str, signature_b64: str, file_ids: list[int] | None = None) -> dict:
        r = await self._post("/messages", json={
            "room_id": room_id,
            "recipient_username": recipient_username,
            "encrypted_blob": encrypted_blob_b64,
            "sender_encrypted_blob": sender_encrypted_blob_b64,
            "signature": signature_b64,
            "file_ids": file_ids or [],
        })
        return r.json()

    async def get_encrypted_messages(self, room_id: int | None = None, since: str | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if room_id is not None:
            params["room_id"] = room_id
        if since is not None:
            params["since"] = since
        r = await self._get("/messages", params=params)
        return r.json()

    async def delete_message(self, message_id: int) -> None:
        await self._delete(f"/messages/{message_id}")

    async def rotate_keys(self) -> None:
        """Rotate X25519 prekey and update backup.
        """
        import base64
        from crypto.key_generator import KeyGenerator
        from crypto.key_backup import KeyBackupManager
        
        if not self.state.ed25519_private or not self.state.x25519_private:
            raise ValueError("No private keys available for rotation")
        
        # Generate new prekey
        new_x25519_priv, new_x25519_pub = KeyGenerator.rotate_prekey(self.state)
        
        # Serialize and encode new public key
        new_x25519_pub_bytes = KeyGenerator.serialize_public_key(new_x25519_pub)
        new_x25519_pub_b64 = base64.b64encode(new_x25519_pub_bytes).decode('utf-8')
        
        # Keep Ed25519 public key unchanged
        ed25519_pub = self.state.ed25519_private.public_key()
        ed25519_pub_bytes = KeyGenerator.serialize_public_key(ed25519_pub)
        ed25519_pub_b64 = base64.b64encode(ed25519_pub_bytes).decode('utf-8')
        
        # Update public keys on server
        await self.update_public_keys(ed25519_pub_b64, new_x25519_pub_b64)
        
        # Re-encrypt backup with new keys
        # Note: For now we only store the new key; in production you might want to
        # include old_x25519_private for a grace period
        backup_manager = KeyBackupManager()
        
        # Get password from user (this would need to be passed as parameter in real implementation)
        # For now, we'll raise an error indicating password is needed
        raise NotImplementedError("Key rotation requires password to re-encrypt backup")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
