"""Tests for protocol versioning between client and server."""

import base64

import pytest
from httpx import AsyncClient
from jose import jwt

from app.auth.version import ProtocolVersionError, get_version_info, negotiate_version
from app.config import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION
from app.services.auth_service import SECRET_KEY, ALGORITHM, create_access_token

# Valid 32-byte keys for registration
_ED25519_PUB_B64 = base64.b64encode(b"\x01" * 32).decode()
_X25519_PUB_B64 = base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


def _reg_payload(username: str, email: str, password: str = "securepass") -> dict:
    """Build a complete registration payload."""
    return {
        "username": username,
        "email": email,
        "password": password,
        "identity_pub_ed25519": _ED25519_PUB_B64,
        "identity_pub_x25519": _X25519_PUB_B64,
        "encrypted_backup": _BACKUP_B64,
    }


# ---------------------------------------------------------------------------
# Version negotiation tests (unit tests)
# ---------------------------------------------------------------------------


async def test_negotiate_version_same_version():
    """Client and server on same version → use that version."""
    agreed = negotiate_version("1.0")
    assert agreed == "1.0"


async def test_negotiate_version_none():
    """Old client without version → use server version (backwards compat)."""
    agreed = negotiate_version(None)
    assert agreed == PROTOCOL_VERSION


async def test_negotiate_version_newer_client():
    """Newer client (2.0) with older server (1.0) → server version (1.0)."""
    agreed = negotiate_version("2.0")
    assert agreed == PROTOCOL_VERSION


async def test_negotiate_version_too_old_client():
    """Too old client (0.5) with server min 1.0 → raise error."""
    with pytest.raises(ProtocolVersionError) as exc_info:
        negotiate_version("0.5")
    assert "not supported" in str(exc_info.value)
    assert exc_info.value.min_version == MIN_PROTOCOL_VERSION
    assert exc_info.value.max_version == PROTOCOL_VERSION


async def test_negotiate_version_partial_version():
    """Client sends version without minor → use it."""
    agreed = negotiate_version("1")
    assert agreed == "1"


async def test_get_version_info():
    """Version info returns correct data."""
    info = get_version_info()
    assert info["server_version"] == PROTOCOL_VERSION
    assert info["min_supported"] == MIN_PROTOCOL_VERSION
    assert info["max_supported"] == PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Login with protocol version tests
# ---------------------------------------------------------------------------


async def test_login_with_valid_version(client: AsyncClient):
    """Login with valid protocol version → success with agreed version."""
    # Register user first
    await client.post(
        "/auth/register",
        json={
            **_reg_payload("versionuser1", "v1@example.com"),
            "protocol_version": "1.0",
        },
    )

    response = await client.post(
        "/auth/login",
        json={
            "username": "versionuser1",
            "password": "securepass",
            "protocol_version": "1.0",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "agreed_version" in data
    assert data["agreed_version"] == "1.0"
    assert "server_min_version" in data
    assert "server_max_version" in data
    assert data["server_min_version"] == MIN_PROTOCOL_VERSION
    assert data["server_max_version"] == PROTOCOL_VERSION


async def test_login_without_version(client: AsyncClient):
    """Login without protocol version → success with server version (backwards compat)."""
    # Register without version
    await client.post("/auth/register", json=_reg_payload("versionuser2", "v2@example.com"))

    response = await client.post(
        "/auth/login",
        json={
            "username": "versionuser2",
            "password": "securepass",
            # No protocol_version field
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "agreed_version" in data
    assert data["agreed_version"] == PROTOCOL_VERSION


async def test_login_with_unsupported_version(client: AsyncClient):
    """Login with unsupported version → 426 Upgrade Required."""
    # Register user first
    await client.post(
        "/auth/register",
        json={
            **_reg_payload("versionuser3", "v3@example.com"),
            "protocol_version": "1.0",
        },
    )

    response = await client.post(
        "/auth/login",
        json={
            "username": "versionuser3",
            "password": "securepass",
            "protocol_version": "0.5",  # Below minimum
        },
    )
    assert response.status_code == 426
    data = response.json()
    assert data["detail"]["error"] == "protocol_version_unsupported"
    assert "min_version" in data["detail"]
    assert "max_version" in data["detail"]


async def test_register_with_version(client: AsyncClient):
    """Register with protocol version → success with agreed version."""
    response = await client.post(
        "/auth/register",
        json={
            **_reg_payload("versionuser4", "v4@example.com"),
            "protocol_version": "1.0",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "agreed_version" in data
    assert data["agreed_version"] == "1.0"
    assert "server_min_version" in data
    assert "server_max_version" in data


async def test_register_with_unsupported_version(client: AsyncClient):
    """Register with unsupported version → 426 Upgrade Required."""
    response = await client.post(
        "/auth/register",
        json={
            **_reg_payload("versionuser5", "v5@example.com"),
            "protocol_version": "0.1",  # Below minimum
        },
    )
    assert response.status_code == 426
    data = response.json()
    assert data["detail"]["error"] == "protocol_version_unsupported"


# ---------------------------------------------------------------------------
# Token with protocol version tests
# ---------------------------------------------------------------------------


async def test_token_contains_protocol_version():
    """Created token should contain protocol version in payload."""
    token = create_access_token(123, "testuser", protocol_version="1.0")
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert "protocol_version" in payload
    assert payload["protocol_version"] == "1.0"
    assert payload["sub"] == "123"
    assert payload["username"] == "testuser"


async def test_protected_endpoint_with_version_header(client: AsyncClient):
    """Access protected endpoint with protocol version header → success."""
    # Register and login to get token
    await client.post(
        "/auth/register",
        json={
            **_reg_payload("versionuser6", "v6@example.com"),
            "protocol_version": "1.0",
        },
    )
    login = await client.post(
        "/auth/login",
        json={
            "username": "versionuser6",
            "password": "securepass",
            "protocol_version": "1.0",
        },
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Protocol-Version": "1.0",
        },
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Version endpoint tests
# ---------------------------------------------------------------------------


async def test_version_endpoint(client: AsyncClient):
    """GET /auth/version returns version info."""
    response = await client.get("/auth/version")
    assert response.status_code == 200
    data = response.json()
    assert "server_version" in data
    assert "min_supported" in data
    assert "max_supported" in data
    assert data["server_version"] == PROTOCOL_VERSION
    assert data["min_supported"] == MIN_PROTOCOL_VERSION
    assert data["max_supported"] == PROTOCOL_VERSION
