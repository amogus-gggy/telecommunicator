"""Integration tests for the users layer (Task 8 checkpoint)."""
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import base64

_ED25519_PUB_B64 = base64.b64encode(b"\x01" * 32).decode()
_X25519_PUB_B64 = base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


async def register_and_login(client: AsyncClient, username: str, email: str, password: str) -> str:
    await client.post("/auth/register", json={
        "username": username, "email": email, "password": password,
        "identity_pub_ed25519": _ED25519_PUB_B64,
        "identity_pub_x25519": _X25519_PUB_B64,
        "encrypted_backup": _BACKUP_B64,
    })
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_me_200(client: AsyncClient):
    token = await register_and_login(client, "usr_alice", "usr_alice@example.com", "password123")
    resp = await client.get("/users/me", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "usr_alice"
    assert data["email"] == "usr_alice@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_patch_me_valid_display_name_200(client: AsyncClient):
    token = await register_and_login(client, "usr_bob", "usr_bob@example.com", "password123")
    resp = await client.patch("/users/me", json={"display_name": "Bobby"}, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Bobby"


@pytest.mark.asyncio
async def test_patch_me_display_name_too_long_422(client: AsyncClient):
    token = await register_and_login(client, "usr_carol", "usr_carol@example.com", "password123")
    long_name = "x" * 65
    resp = await client.patch("/users/me", json={"display_name": long_name}, headers=auth(token))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_password_correct_current_200(client: AsyncClient):
    token = await register_and_login(client, "usr_dave", "usr_dave@example.com", "password123")
    resp = await client.post(
        "/users/me/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
        headers=auth(token),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current_401(client: AsyncClient):
    token = await register_and_login(client, "usr_eve", "usr_eve@example.com", "password123")
    resp = await client.post(
        "/users/me/password",
        json={"current_password": "wrongpassword", "new_password": "newpassword456"},
        headers=auth(token),
    )
    assert resp.status_code == 401
