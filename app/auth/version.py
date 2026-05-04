"""Protocol version negotiation and validation."""

from __future__ import annotations

from app.config import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION


def negotiate_version(client_version: str | None) -> str:
    """Negotiate protocol version between client and server.

    Args:
        client_version: Protocol version reported by client (can be None for old clients)

    Returns:
        Agreed protocol version string

    Raises:
        ProtocolVersionError: If client version is incompatible
    """
    server_version = PROTOCOL_VERSION
    server_min = MIN_PROTOCOL_VERSION

    # If client didn't send version, assume server version (backwards compatibility)
    if client_version is None:
        return server_version

    # Parse versions (simple "major.minor" format)
    try:
        client_parts = tuple(int(x) for x in client_version.split("."))
        server_parts = tuple(int(x) for x in server_version.split("."))
        server_min_parts = tuple(int(x) for x in server_min.split("."))
    except (ValueError, AttributeError):
        # Invalid version format, fall back to server version
        return server_version

    # Normalize tuple lengths by padding with zeros for comparison
    max_len = max(len(client_parts), len(server_parts), len(server_min_parts))
    client_norm = client_parts + (0,) * (max_len - len(client_parts))
    server_norm = server_parts + (0,) * (max_len - len(server_parts))
    server_min_norm = server_min_parts + (0,) * (max_len - len(server_min_parts))

    # Check if client version is too old
    if client_norm < server_min_norm:
        raise ProtocolVersionError(
            f"Client version {client_version} is not supported. "
            f"Minimum required: {server_min}",
            min_version=server_min,
            max_version=server_version,
        )

    # Check if client version is newer than server (server needs to upgrade)
    if client_norm > server_norm:
        # Client is newer - server will use its max version
        return server_version

    # Client version is compatible, use it
    return client_version


def get_version_info() -> dict:
    """Get server version information."""
    return {
        "server_version": PROTOCOL_VERSION,
        "min_supported": MIN_PROTOCOL_VERSION,
        "max_supported": PROTOCOL_VERSION,
    }


class ProtocolVersionError(Exception):
    """Raised when client protocol version is incompatible."""

    def __init__(
        self, message: str, min_version: str, max_version: str
    ) -> None:
        super().__init__(message)
        self.min_version = min_version
        self.max_version = max_version
