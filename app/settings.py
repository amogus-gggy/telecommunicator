import os

# How well this server is reached from the outside. One variable drives both
# the federated identity and the reachable API address.
#
# Formats:
#   "host:port"      -> http://host:port     (e.g. "127.0.0.1:8000")
#   "host"           -> http://host:8000
#   "https://h:p"    -> https://host:p       (kept as-is)
#   "http://h:p"     -> http://host:p

SERVER_ADDRESS: str = os.getenv("SERVER_ADDRESS", "").strip()

if not SERVER_ADDRESS:
    # Backwards-compatible fallback for configurations that set the two
    # variables separately.
    SERVER_NAME: str = os.getenv("SERVER_NAME", "127.0.0.1:8000")
    SERVER_BASE_URL: str = os.getenv(
        "SERVER_BASE_URL", "http://127.0.0.1:8000"
    ).rstrip("/")
else:
    _addr = SERVER_ADDRESS.strip().rstrip("/")
    if "://" in _addr:
        _scheme, _netloc = _addr.split("://", 1)
        _scheme = _scheme.lower() or "http"
    else:
        _scheme = "http"
        _netloc = _addr

    # Give the identity a durable host:port form even when the port is omitted.
    if ":" not in _netloc:
        _default_port = 443 if _scheme == "https" else 8000
        _netloc = f"{_netloc}:{_default_port}"

    SERVER_NAME: str = _netloc
    SERVER_BASE_URL: str = f"{_scheme}://{_netloc}"