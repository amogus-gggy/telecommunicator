"""Server-to-server federation: identity, signed transport, user resolution.

All cross-server traffic flows through the server the user is logged in to:
the client only talks to its local server, which in turn talks to other
homeservers over signed federation HTTP endpoints (``/federation/*``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.models.user import User
from app.settings import SERVER_BASE_URL, SERVER_NAME

logger = logging.getLogger(__name__)

_FED_DEFAULT_PORT = 8000
# Max acceptable skew (seconds) between X-Federation-Date and this node's clock.
# Rejects replays of old signed requests; generous enough for slow peers / clocks.
_FED_MAX_TIMESTAMP_SKEW_SECONDS = 15 * 60
# A server identifier may only be a host[:port] — no scheme, path, query, userinfo.
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+(?::\d{1,5})?$")

# ---------------------------------------------------------------------------
# Transport (shared clients per remote base_url, test-transport injectable)
# ---------------------------------------------------------------------------

_clients: dict[str, httpx.AsyncClient] = {}
_test_transport: httpx.AsyncBaseTransport | None = None


def set_federation_test_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Install a custom transport (e.g. httpx ASGITransport) for tests."""
    global _test_transport
    _test_transport = transport
    _clients.clear()


async def close_federation_clients() -> None:
    for client in _clients.values():
        await client.aclose()
    _clients.clear()


def _client_for(base_url: str) -> httpx.AsyncClient:
    if base_url not in _clients:
        client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            transport=_test_transport,
        )
        _clients[base_url] = client
    return _clients[base_url]


# ---------------------------------------------------------------------------
# Identity / signatures
# ---------------------------------------------------------------------------


def _generate_keypair() -> tuple[bytes, bytes]:
    """Return (public_key, private_key) for a fresh Ed25519 keypair."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    return (
        private.public_key().public_bytes_raw(),
        private.private_bytes_raw(),
    )


async def get_local_server(db: AsyncSession) -> Server:
    """Return (creating if needed) the row describing this homeserver."""
    result = await db.execute(
        select(Server).where(Server.server_name == SERVER_NAME)
    )
    server = result.scalar_one_or_none()
    if server is not None:
        return server

    public_key, private_key = _generate_keypair()
    server = Server(
        server_name=SERVER_NAME,
        base_url=SERVER_BASE_URL,
        is_local=True,
        public_key=public_key,
        private_key=private_key,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


async def get_local_public_key(db: AsyncSession) -> bytes:
    server = await get_local_server(db)
    return server.public_key or b""


def _signature_canonical(method: str, path: str, date: str, body: bytes) -> str:
    body_digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    return f"{method}\n{path}\n{date}\n{body_digest}"


def _sign(server: Server, canonical: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not server.private_key:
        raise RuntimeError("local server has no private key")
    private = Ed25519PrivateKey.from_private_bytes(server.private_key)
    sig = private.sign(canonical.encode())
    return base64.b64encode(sig).decode()


def _verify(server: Server, canonical: str, signature_b64: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not server.public_key:
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(server.public_key)
        public.verify(base64.b64decode(signature_b64), canonical.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


async def _sign_headers(
    db: AsyncSession, method: str, path: str, body: bytes
) -> dict[str, str]:
    server = await get_local_server(db)
    date = datetime.now(timezone.utc).isoformat()
    canonical = _signature_canonical(method, path, date, body)
    return {
        "X-Federation-Server": SERVER_NAME,
        "X-Federation-Date": date,
        "X-Federation-Signature": _sign(server, canonical),
        "Content-Type": "application/json",
    }


def _parse_federation_date(date: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid federation timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_valid_server_name(name: str) -> bool:
    """A sender/handle server name must be a bare ``host[:port]``.

    Anything containing a scheme, path, whitespace or other characters would let
    a remote (or a client-supplied handle) steer this node's HTTP client at an
    arbitrary URL — blocked here.
    """
    return bool(name) and len(name) <= 255 and bool(_SERVER_NAME_RE.match(name))


async def verify_request(
    db: AsyncSession, request: Request, body: bytes
) -> Server:
    """Verify that ``request`` carries a valid signature from a known server.

    On first contact from an unknown server its public key is bootstrapped via
    its ``/federation/hello`` (TOFU), so the very first signed request to us
    succeeds instead of being rejected as unknown.
    """
    sender = request.headers.get("X-Federation-Server", "")
    date = request.headers.get("X-Federation-Date", "")
    signature = request.headers.get("X-Federation-Signature", "")
    if not sender or not date or not signature:
        raise HTTPException(status_code=403, detail="Missing federation headers")
    if not _is_valid_server_name(sender):
        raise HTTPException(status_code=403, detail="Invalid federation server name")

    request_dt = _parse_federation_date(date)
    if (
        abs((datetime.now(timezone.utc) - request_dt).total_seconds())
        > _FED_MAX_TIMESTAMP_SKEW_SECONDS
    ):
        raise HTTPException(
            status_code=403, detail="Federation timestamp too old or in the future"
        )

    result = await db.execute(select(Server).where(Server.server_name == sender))
    server = result.scalar_one_or_none()
    if server is None:
        server = await _discover_server(db, sender)
        if server is None:
            raise HTTPException(status_code=403, detail="Unknown federation server")

    canonical = _signature_canonical(
        request.method, request.url.path, date, body
    )
    if not _verify(server, canonical, signature):
        raise HTTPException(status_code=403, detail="Invalid federation signature")

    return server


# ---------------------------------------------------------------------------
# Discovery / server registry
# ---------------------------------------------------------------------------


def _default_base_url(server_name: str) -> str | None:
    """Build a base URL for a validated bare ``host[:port]`` server name.

    Returns ``None`` when ``server_name`` is not a plain host[:port] — a scheme,
    a path or any other character would otherwise let a remote (or a client
    handle) redirect this node's HTTP client at an arbitrary URL.
    """
    if not _is_valid_server_name(server_name):
        return None
    if ":" in server_name:
        return f"http://{server_name}"
    return f"http://{server_name}:{_FED_DEFAULT_PORT}"


async def _discover_server(
    db: AsyncSession, server_name: str
) -> Server | None:
    """Look up a remote server's public key via its ``/federation/hello`` (TOFU).

    The remote reports its own canonical ``server_name`` — we key the registry
    row and cached users by THAT, not by the host we were given (avoids e.g.
    ``localhost:8011`` vs ``127.0.0.1:8011`` splitting one server in two).
    Returns ``None`` when the remote cannot be reached or returns no key.
    """
    base_url = _default_base_url(server_name)
    if base_url is None:
        return None
    try:
        client = _client_for(base_url)
        response = await client.post(
            "/federation/hello",
            json={"server_name": server_name},
            timeout=10.0,
        )
        response.raise_for_status()
        info = response.json()
    except Exception as exc:
        logger.warning("[Federation] Failed to discover %s: %s", server_name, exc)
        return None

    reported = (info.get("server_name") or server_name).strip()
    canonical = reported if _is_valid_server_name(reported) else server_name
    public_key = None
    try:
        public_key = base64.b64decode(info.get("public_key", ""))
    except Exception:
        public_key = None

    existing = await db.execute(
        select(Server).where(Server.server_name == canonical)
    )
    server = existing.scalar_one_or_none()
    if server is not None:
        return server

    reported_base = (info.get("base_url") or "").strip().rstrip("/")
    if not re.match(r"^https?://[^\s/?#]+(?:/.*)?$", reported_base):
        reported_base = base_url

    server = Server(
        server_name=canonical,
        base_url=reported_base,
        is_local=False,
        public_key=public_key if public_key else None,
    )
    db.add(server)
    # Remove any row previously created under an alias of the same server.
    if canonical != server_name:
        await db.execute(delete(Server).where(Server.server_name == server_name))
    await db.commit()
    await db.refresh(server)
    return server


async def ensure_server(db: AsyncSession, server_name: str) -> Server:
    """Return the registry row for ``server_name``, bootstrapping it if unknown."""
    result = await db.execute(select(Server).where(Server.server_name == server_name))
    server = result.scalar_one_or_none()
    if server is not None:
        return server

    server = await _discover_server(db, server_name)
    if server is None:
        raise HTTPException(
            status_code=502, detail=f"Cannot reach federation server {server_name}"
        )
    return server


async def send_to_server(
    db: AsyncSession,
    server: Server,
    method: str,
    path: str,
    body: dict,
) -> httpx.Response:
    """Send a signed federation request to ``server`` and raise on HTTP errors."""
    raw = json.dumps(body).encode()
    headers = await _sign_headers(db, method, path, raw)
    client = _client_for(server.base_url)
    try:
        response = await client.request(method, path, headers=headers, content=raw)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Federation request to {server.server_name} failed: {exc}",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Federation request to {server.server_name} failed: "
                f"{response.status_code} {response.text[:300]}"
            ),
        )
    return response


async def send_room_message(
    db: AsyncSession,
    server: Server,
    room_id_on_server: int,
    sender_member: dict,
    payload: dict,
) -> None:
    """Relay a room message (with its author) to a specific remote homeserver."""
    await send_to_server(
        db,
        server,
        "POST",
        f"/federation/rooms/{room_id_on_server}/message",
        {"sender": sender_member, "payload": payload},
    )


async def import_room_to_server(
    db: AsyncSession, server: Server, body: dict
) -> int:
    """Ask ``server`` to create a local mirror room; returns the mirror's PK."""
    response = await send_to_server(
        db, server, "POST", "/federation/rooms/import", body
    )
    info = response.json()
    link_id = info.get("local_room_id")
    if not isinstance(link_id, int):
        raise HTTPException(status_code=502, detail="Remote import failed")
    return link_id


def user_member_payload(user: User) -> dict:
    """Serialize a user for a federation member list."""

    def _b64(data: bytes | None) -> str | None:
        return base64.b64encode(data).decode() if data else None

    return {
        "username": user.username,
        "server_name": user.server_name,
        "display_name": user.display_name,
        "identity_pub_ed25519": _b64(user.identity_pub_ed25519),
        "identity_pub_x25519": _b64(user.identity_pub_x25519),
    }


# ---------------------------------------------------------------------------
# Handles & user resolution
# ---------------------------------------------------------------------------


def parse_handle(handle: str) -> tuple[str, str]:
    """Split ``username@server`` into (username, server_name).

    The last ``@`` wins. A bare username resolves to the local server.
    """
    handle = (handle or "").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="Empty user handle")
    if "@" in handle:
        username, server_name = handle.rsplit("@", 1)
        if not username:
            raise HTTPException(status_code=400, detail="Empty username in handle")
        return username, server_name
    return handle, SERVER_NAME


def is_remote_server(server_name: str) -> bool:
    return server_name != SERVER_NAME


async def find_local_user(
    db: AsyncSession, username: str, server_name: str | None = None
) -> User | None:
    """Find a user by username; scoped to the local server unless remote given."""
    if server_name is None:
        _, server_name = parse_handle(username)
    result = await db.execute(
        select(User).where(
            User.username == username, User.server_name == server_name
        )
    )
    return result.scalar_one_or_none()


async def cache_remote_user(
    db: AsyncSession,
    username: str,
    server_name: str,
    *,
    display_name: str | None = None,
    identity_pub_ed25519: bytes | None = None,
    identity_pub_x25519: bytes | None = None,
) -> User:
    """Upsert a cached row for a remote user."""
    result = await db.execute(
        select(User).where(
            User.username == username, User.server_name == server_name
        )
    )
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        username=username,
        server_name=server_name,
        is_remote=True,
        email=f"{uuid.uuid4().hex}@remote.{server_name}",
        hashed_password="!",
        display_name=display_name,
        identity_pub_ed25519=identity_pub_ed25519,
        identity_pub_x25519=identity_pub_x25519,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def resolve_user(
    db: AsyncSession, handle: str
) -> User:
    """Resolve a handle to a local or (cached/remotely-looked-up) remote user.

    For remote handles the caller's server contacts the remote homeserver to
    fetch the user's profile and E2EE keys before returning the cached row.
    """
    username, server_name = parse_handle(handle)

    if not is_remote_server(server_name):
        user = await find_local_user(db, username, SERVER_NAME)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    # Already cached?
    cached = await find_local_user(db, username, server_name)
    if cached is not None:
        return cached

    server = await ensure_server(db, server_name)
    # The remote's canonical name (its own /federation/hello identity) wins —
    # the handle host is only a hint to reach it.
    canonical = server.server_name
    if canonical != server_name:
        cached = await find_local_user(db, username, canonical)
        if cached is not None:
            return cached

    response = await send_to_server(
        db,
        server,
        "POST",
        "/federation/user/lookup",
        {"username": username},
    )
    info = response.json()
    if not info.get("found"):
        raise HTTPException(status_code=404, detail="User not found")

    def _decode_b64(value: str | None) -> bytes | None:
        if not value:
            return None
        try:
            return base64.b64decode(value)
        except Exception:
            return None

    return await cache_remote_user(
        db,
        username,
        canonical,
        display_name=info.get("display_name"),
        identity_pub_ed25519=_decode_b64(info.get("identity_pub_ed25519")),
        identity_pub_x25519=_decode_b64(info.get("identity_pub_x25519")),
    )


def user_payload(user: User) -> dict:
    """Serialize a user for a federation lookup response."""
    def _b64(data: bytes | None) -> str | None:
        return base64.b64encode(data).decode() if data else None

    return {
        "username": user.username,
        "server_name": user.server_name,
        "display_name": user.display_name,
        "identity_pub_ed25519": _b64(user.identity_pub_ed25519),
        "identity_pub_x25519": _b64(user.identity_pub_x25519),
    }
