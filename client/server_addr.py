from __future__ import annotations

from urllib.parse import urlparse

DEFAULT_HTTP_PORT = 8000


def parse_handle(handle: str) -> tuple[str, str | None]:
    """Split 'username@server' into (username, server).

    Returns ``(handle, None)`` when no ``@`` is present — in that case the
    current/default server is used. The last ``@`` wins so the format works
    even if usernames ever contain the symbol.
    """
    handle = (handle or "").strip()
    if not handle:
        return "", None
    if "@" in handle:
        username, server = handle.rsplit("@", 1)
        return username.strip(), (server or "").strip() or None
    return handle, None


def build_api_urls(server: str) -> tuple[str, str]:
    """Normalize a server address into ``(api_url, ws_url)``.

    Accepts bare hosts (``example.com``), ``host:port`` pairs and full URLs
    with a scheme. When the scheme is omitted ``http`` is assumed and when no
    port is given it defaults to 8000 (the app's standard port).
    """
    server = (server or "").strip().rstrip("/")
    if not server:
        raise ValueError("server address is empty")
    if "://" not in server:
        server = f"http://{server}"
    parsed = urlparse(server)
    if not parsed.netloc:
        raise ValueError(f"invalid server address: {server!r}")
    if parsed.port is None:
        default_port = DEFAULT_HTTP_PORT if parsed.scheme in ("http", "ws") else 443
        server = f"{parsed.scheme}://{parsed.netloc}:{default_port}{parsed.path}"
    proto, rest = server.split("://", 1)
    if proto == "http":
        ws_proto = "ws"
    elif proto == "https":
        ws_proto = "wss"
    else:
        ws_proto = proto
    return server, f"{ws_proto}://{rest}/ws"
