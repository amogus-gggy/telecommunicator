# Telecommunicator - AI Agent Guide

## Project Overview

Telecommunicator is a **self-hosted secure messenger** with end-to-end encryption (E2EE). It consists of:

- **Server**: FastAPI-based backend with SQLite database
- **Client**: Flet-based cross-platform desktop/mobile app
- **Features**: Encrypted messaging, file sharing, rooms/channels, SSH deployment, backups

## Architecture

```
┌─────────────────┐      HTTP/WebSocket      ┌─────────────────┐
│   Client (Flet) │  ◄─────────────────────►  │  Server (FastAPI)│
│   Python + UI   │      E2EE Messages       │  SQLite + SQLAlch│
└─────────────────┘                           └─────────────────┘
```

## Directory Structure

| Path | Purpose |
|------|---------|
| `app/` | Server-side FastAPI application |
| `app/routers/` | API endpoints (auth, messages, rooms, ws, backup) |
| `app/models/` | SQLAlchemy database models (User, Room, Message, File, RoomMember) |
| `app/services/` | Business logic layer |
| `app/schemas/` | Pydantic request/response models |
| `app/ws/` | WebSocket connection manager |
| `app/auth/` | JWT authentication utilities |
| `app/db/` | Database engine, dependencies, base model |
| `app/config.py` | Server configuration dataclasses |
| `client/` | Flet-based client application |
| `client/views/` | UI view modules (login, chat, rooms, profile, deploy) |
| `client/api/` | HTTP client and WebSocket client |
| `client/crypto/` | E2EE implementation (Ed25519/X25519, file crypto, key management) |
| `client/storage/` | Local settings storage |
| `client/deployer/` | SSH-based server deployment tools |
| `alembic/` | Database migration scripts |
| `tests/` | pytest test suite |

## Key Technologies

**Server:**
- FastAPI 0.136 + Uvicorn
- SQLAlchemy 2.0 (async) + aiosqlite
- Alembic for migrations
- python-jose + passlib (JWT/bcrypt auth)
- python-multipart (file uploads)
- WebSockets (real-time messaging)

**Client:**
- Flet 0.84 (Flutter-based Python UI)
- httpx (HTTP client)
- cryptography library (E2EE)

**Crypto:**
- Ed25519 for message signing
- X25519 for key exchange
- AES-GCM for file encryption

## Running the Project

**Server:**
```bash
# Default config
python run_server.py

# Custom port/host
python run_server.py --host 0.0.0.0 --port 8080

# With explicit config
python run_server.py --config custom_config.json

# Show current config
python run_server.py --show-config
```

**Client:**
```bash
cd client
python main.py
```

**Tests:**
```bash
pytest
```

## Configuration

**Server** (`server_config.json` or env `SERVER_CONFIG_PATH`):
- `server_name`, `server_description` — Server identity
- `allow_file_uploads`, `allow_voice_messages` — Feature toggles
- `enable_encryption` — E2EE support flag
- `limits.max_users`, `limits.max_rooms_per_user` — Resource limits
- `limits.file_upload.max_file_size_mb` — Upload limits
- `security.allow_registration`, `security.token_expire_hours` — Auth settings

See `server_config.example.json` for full structure.

## Database Models

| Model | Key Fields |
|-------|-----------|
| `User` | id, username, email, hashed_password, is_admin |
| `Room` | id, name, type (personal/group), owner_id, encrypted_key |
| `RoomMember` | room_id, user_id, role, joined_at |
| `Message` | id, room_id, sender_id, encrypted_content, encrypted_key_for_room |
| `File` | id, room_id, uploader_id, filename, encrypted_path, encryption_metadata |

**E2EE Fields:**
- `encrypted_content` — Message ciphertext
- `encrypted_key_for_room` — Room key encrypted for sender
- `sender_encrypted_blob` — Sender's own encrypted copy
- `encryption_metadata` — File encryption parameters (iv, tag, encrypted_key)

## API Structure

| Router | Endpoints |
|--------|-----------|
| `auth.py` | POST /auth/register, /auth/login, /auth/me |
| `rooms.py` | CRUD rooms, members, join/leave, kick |
| `messages.py` | POST/GET messages, upload/download files |
| `users.py` | GET/PUT user profile, search |
| `ws.py` | WebSocket for real-time events |
| `backup.py` | Export/restore encrypted backups |
| `server.py` | Server info, protocol version |

## Client Architecture

**State Management:**
- `AppState` dataclass holds: api_url, ws_url, token, current_user, active_room, ws connection, crypto keys
- `LocalStorage` for persistent settings (SQLite on desktop, file-based fallback)

**Crypto Flow:**
1. `key_generator.py` — Generate Ed25519/X25519 keypairs
2. `message_crypto.py` — Encrypt/sign messages, verify signatures
3. `file_crypto.py` — Stream-encrypt large files with AES-GCM
4. `key_cache.py` — Cache other users' public keys
5. `key_backup.py` — Export encrypted key bundles

**Views:**
- `login_view.py` — Server selection, auth
- `register_view.py` — Account creation
- `chat_list_view.py` — Conversation list
- `room_view.py` — Active chat (messages, file upload, encryption UI)
- `room_settings_view.py` — Room management
- `profile_view.py` — User settings, key backup/restore
- `server_deploy_view.py` — SSH deployment to remote server

## WebSocket Protocol

**Connection:** `wss://server/ws?token=<jwt>`

**Client → Server:**
```json
{"type": "subscribe", "room_id": 123}
{"type": "ping"}
```

**Server → Client:**
```json
{"type": "message", "room_id": 123, "payload": {...}}
{"type": "notification", "notification_type": "new_message", "data": {...}}
{"type": "error", "message": "..."}
```

## Protocol Versioning

- Client and server negotiate protocol version on connection
- `PROTOCOL_VERSION = "1.0"` (client), server returns `min_version`/`max_version`
- Used for feature detection (E2EE, file uploads, etc.)

## Key Conventions

1. **E2EE is optional per room** — `is_encrypted` flag on room
2. **All file uploads are encrypted** — Server stores only ciphertext
3. **Async everywhere** — Both server (FastAPI) and client (Flet) use async/await
4. **Type hints required** — All functions have annotations
5. **Logging pattern** — `logger = logging.getLogger(__name__)` with brackets: `[Module] message`
6. **Error handling** — Custom exceptions in `http_client.py`: `APIError`, `AuthError`, `ValidationError`

## Common Tasks

**Adding a new API endpoint:**
1. Add Pydantic schema in `app/schemas/`
2. Add service method in `app/services/`
3. Add router handler in `app/routers/`
4. Include router in `app/main.py`
5. Add client method in `client/api/http_client.py`
6. Add/update tests in `tests/`

**Adding a database field:**
1. Update model in `app/models/`
2. Create Alembic migration: `alembic revision --autogenerate -m "description"`
3. Update schemas if exposed in API
4. Update service layer

**Adding a client view:**
1. Create file in `client/views/`
2. Import and call from parent view
3. Update `main.py` `_preload_views()` for Android startup
4. Add localization strings to `client/locales/`

## Testing

- **Fixtures** in `conftest.py`: async db session, test client, authenticated user
- **Hypothesis** property-based testing for crypto and protocol tests
- **Async tests** use `pytest-asyncio`
- Run: `pytest -v` or `pytest tests/test_rooms.py -v`

## Security Notes

- Never log raw encryption keys
- Server never sees plaintext message content (E2EE)
- File encryption uses unique IV per file
- Key backups are password-encrypted before export

## Deployment

The client includes `server_deploy_view.py` for one-click server deployment:
- SSH connection to VPS
- Docker or bare-metal setup
- Automatic SSL with Let's Encrypt (optional)

## Development Tips

- Server auto-reload: `python run_server.py --reload`
- Client hot reload: Flet handles this automatically
- Reset database: delete `messenger.db` and run migrations
- Clear client storage: delete `client/storage/data/` directory
