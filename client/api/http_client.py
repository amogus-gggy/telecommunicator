from __future__ import annotations

from typing import Any

import httpx

from client.config import API_URL
from client.state import AppState


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
    async def register(self, username: str, email: str, password: str) -> dict:
        r = await self._post("/auth/register", json={"username": username, "email": email, "password": password})
        return r.json()

    async def login(self, username: str, password: str) -> dict:
        r = await self._post("/auth/login", json={"username": username, "password": password})
        return r.json()

    async def logout(self) -> None:
        self.state.token = None
        self.state.current_user = None
        self.state.active_room = None

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

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
