"""Unit tests for client/api/http_client.py."""
from __future__ import annotations

import json

import httpx
import pytest

from client.api.http_client import (
    APIClient,
    APIError,
    AuthError,
    ConflictError,
    ForbiddenError,
    ValidationError,
    _parse_detail,
    _raise_for_status,
)
from client.state import AppState


def _make_response(status_code: int, body: dict | str | None = None) -> httpx.Response:
    if body is None:
        content = b""
        headers = {}
    elif isinstance(body, dict):
        content = json.dumps(body).encode()
        headers = {"content-type": "application/json"}
    else:
        content = body.encode()
        headers = {}
    return httpx.Response(status_code=status_code, content=content, headers=headers)


# _parse_detail tests

def test_parse_detail_string():
    r = _make_response(400, {"detail": "something went wrong"})
    assert _parse_detail(r) == "something went wrong"


def test_parse_detail_list():
    r = _make_response(422, {"detail": [{"msg": "field required"}, {"msg": "too short"}]})
    assert _parse_detail(r) == "field required; too short"


def test_parse_detail_non_json():
    r = _make_response(500, "Internal Server Error")
    assert _parse_detail(r) == "Internal Server Error"


# _raise_for_status tests

def test_raise_401():
    r = _make_response(401, {"detail": "Token expired"})
    with pytest.raises(AuthError) as exc_info:
        _raise_for_status(r)
    assert exc_info.value.status_code == 401


def test_raise_403():
    r = _make_response(403, {"detail": "Forbidden"})
    with pytest.raises(ForbiddenError) as exc_info:
        _raise_for_status(r)
    assert exc_info.value.status_code == 403


def test_raise_409():
    r = _make_response(409, {"detail": "Username already exists"})
    with pytest.raises(ConflictError) as exc_info:
        _raise_for_status(r)
    assert exc_info.value.status_code == 409


def test_raise_422():
    r = _make_response(422, {"detail": [{"msg": "value is too short"}]})
    with pytest.raises(ValidationError) as exc_info:
        _raise_for_status(r)
    assert exc_info.value.status_code == 422


def test_raise_500():
    r = _make_response(500, {"detail": "Internal error"})
    with pytest.raises(APIError) as exc_info:
        _raise_for_status(r)
    assert exc_info.value.status_code == 500


def test_no_raise_on_200():
    r = _make_response(200, {"access_token": "abc"})
    _raise_for_status(r)  # should not raise


# APIClient tests

class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._handler(request)


@pytest.mark.asyncio
async def test_token_attached_in_header():
    state = AppState(token="test-jwt-token")
    client = APIClient(base_url="http://localhost:8000", state=state)
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _make_response(200, {"id": 1, "username": "alice", "email": "a@b.com", "display_name": None})

    client._client = httpx.AsyncClient(base_url="http://localhost:8000", transport=MockTransport(handler))
    await client.get_me()
    assert captured[0].headers.get("authorization") == "Bearer test-jwt-token"
    await client.aclose()


@pytest.mark.asyncio
async def test_no_auth_header_when_no_token():
    state = AppState(token=None)
    client = APIClient(base_url="http://localhost:8000", state=state)
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _make_response(200, {"access_token": "tok", "token_type": "bearer"})

    client._client = httpx.AsyncClient(base_url="http://localhost:8000", transport=MockTransport(handler))
    await client.login("alice", "password123")
    assert "authorization" not in captured[0].headers
    await client.aclose()


@pytest.mark.asyncio
async def test_login_raises_auth_error_on_401():
    state = AppState()
    client = APIClient(base_url="http://localhost:8000", state=state)

    async def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(401, {"detail": "Invalid credentials"})

    client._client = httpx.AsyncClient(base_url="http://localhost:8000", transport=MockTransport(handler))
    with pytest.raises(AuthError):
        await client.login("alice", "wrongpass")
    await client.aclose()


@pytest.mark.asyncio
async def test_register_raises_conflict_on_409():
    state = AppState()
    client = APIClient(base_url="http://localhost:8000", state=state)

    async def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(409, {"detail": "Username already exists"})

    client._client = httpx.AsyncClient(base_url="http://localhost:8000", transport=MockTransport(handler))
    with pytest.raises(ConflictError) as exc_info:
        await client.register("alice", "a@b.com", "password123")
    assert "Username already exists" in exc_info.value.message
    await client.aclose()


@pytest.mark.asyncio
async def test_logout_clears_state():
    from client.state import RoomDTO, UserDTO
    state = AppState(
        token="tok",
        current_user=UserDTO(id=1, username="alice", email="a@b.com"),
        active_room=RoomDTO(id=1, name="general", room_type="group", owner_username="alice", member_count=1, is_private=False, allow_member_invite=False, read_only=False),
    )
    client = APIClient(base_url="http://localhost:8000", state=state)
    await client.logout()
    assert state.token is None
    assert state.current_user is None
    assert state.active_room is None
    await client.aclose()
