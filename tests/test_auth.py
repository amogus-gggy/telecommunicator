"""Integration tests for the auth layer."""

import base64

from httpx import AsyncClient

from app.services.auth_service import create_access_token

# Valid 32-byte keys encoded as base64 for use in registration payloads
_ED25519_PUB_B64 = base64.b64encode(b"\x01" * 32).decode()
_X25519_PUB_B64 = base64.b64encode(b"\x02" * 32).decode()
_BACKUP_B64 = base64.b64encode(b"\x03" * 64).decode()


def _reg_payload(username: str, email: str, password: str = "securepass") -> dict:
    """Build a complete registration payload including E2EE fields."""
    return {
        "username": username,
        "email": email,
        "password": password,
        "identity_pub_ed25519": _ED25519_PUB_B64,
        "identity_pub_x25519": _X25519_PUB_B64,
        "encrypted_backup": _BACKUP_B64,
    }


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


async def test_register_new_user(client: AsyncClient):
    """Register a new user → 201 with user_id and username."""
    response = await client.post(
        "/auth/register", json=_reg_payload("alice", "alice@example.com")
    )
    assert response.status_code == 201
    data = response.json()
    assert "user_id" in data
    assert data["username"] == "alice"


async def test_register_duplicate_username(client: AsyncClient):
    """Register duplicate username → 409."""
    await client.post("/auth/register", json=_reg_payload("bob", "bob@example.com"))

    response = await client.post(
        "/auth/register", json=_reg_payload("bob", "bob2@example.com")
    )
    assert response.status_code == 409


async def test_register_duplicate_email(client: AsyncClient):
    """Register duplicate email → 409."""
    await client.post("/auth/register", json=_reg_payload("carol", "carol@example.com"))

    response = await client.post(
        "/auth/register", json=_reg_payload("carol2", "carol@example.com")
    )
    assert response.status_code == 409


async def test_register_short_password(client: AsyncClient):
    """Register with password < 8 chars → 422."""
    response = await client.post(
        "/auth/register",
        json=_reg_payload("dave", "dave@example.com", password="short"),
    )
    assert response.status_code == 422


async def test_register_invalid_ed25519_key_size(client: AsyncClient):
    """Register with Ed25519 key that is not 32 bytes → 400."""
    payload = _reg_payload("eve2", "eve2@example.com")
    payload["identity_pub_ed25519"] = base64.b64encode(
        b"\x01" * 16
    ).decode()  # 16 bytes, invalid
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 400


async def test_register_invalid_x25519_key_size(client: AsyncClient):
    """Register with X25519 key that is not 32 bytes → 400."""
    payload = _reg_payload("eve3", "eve3@example.com")
    payload["identity_pub_x25519"] = base64.b64encode(
        b"\x02" * 64
    ).decode()  # 64 bytes, invalid
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


async def test_login_valid_credentials(client: AsyncClient):
    """Login with valid credentials → 200 with access_token."""
    await client.post("/auth/register", json=_reg_payload("eve", "eve@example.com"))

    response = await client.post(
        "/auth/login",
        json={
            "username": "eve",
            "password": "securepass",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["encrypted_backup"] == _BACKUP_B64
    assert data["user_id"] is not None
    assert data["username"] == "eve"


async def test_login_wrong_password(client: AsyncClient):
    """Login with wrong password → 401."""
    await client.post("/auth/register", json=_reg_payload("frank", "frank@example.com"))

    response = await client.post(
        "/auth/login",
        json={
            "username": "frank",
            "password": "wrongpassword",
        },
    )
    assert response.status_code == 401


async def test_login_unknown_username(client: AsyncClient):
    """Login with unknown username → 401."""
    response = await client.post(
        "/auth/login",
        json={
            "username": "nobody",
            "password": "securepass",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoint tests
# ---------------------------------------------------------------------------


async def test_protected_endpoint_no_token(client: AsyncClient):
    """Access protected endpoint without token → 401."""
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_protected_endpoint_expired_token(client: AsyncClient):
    """Access protected endpoint with expired token → 401."""
    # Register a user first so the user exists in DB
    reg = await client.post(
        "/auth/register", json=_reg_payload("grace", "grace@example.com")
    )
    user_id = reg.json()["user_id"]

    # Create a token that is already expired (expire_hours=0 means immediate expiry)
    expired_token = create_access_token(user_id, "grace", expire_hours=-1)

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401
