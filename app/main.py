import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    """Apply all pending Alembic migrations before the app starts (non-blocking).

    If the alembic directory doesn't exist, initializes it first.
    Migration failures are logged but don't crash the server.
    """
    loop = asyncio.get_event_loop()

    def _run_migrations_sync() -> None:
        # Ensure alembic is initialized
        if not Path("alembic").exists() or not Path("alembic.ini").exists():
            logger.info("[Migrations] Alembic not initialized, running 'alembic init'...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "alembic", "init", "alembic"],
                    check=False,
                    capture_output=True,
                )
            except Exception as e:
                logger.warning(f"[Migrations] Failed to init alembic: {e}")
                return

        # Run migrations
        logger.info("[Migrations] Running 'alembic upgrade head'...")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                f"[Migrations] Alembic upgrade failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )
        else:
            logger.info("[Migrations] Alembic migrations applied successfully")

    await loop.run_in_executor(None, _run_migrations_sync)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    yield


app = FastAPI(title="Telecommunicator", lifespan=lifespan)

from app.routers import auth as auth_router  # noqa: E402
from app.routers import backup as backup_router  # noqa: E402
from app.routers import messages as messages_router  # noqa: E402
from app.routers import rooms as rooms_router  # noqa: E402
from app.routers import server as server_router  # noqa: E402
from app.routers import users as users_router  # noqa: E402
from app.routers import ws as ws_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(rooms_router.router)
app.include_router(messages_router.router)
app.include_router(users_router.router)
app.include_router(ws_router.router)
app.include_router(backup_router.router)
app.include_router(server_router.router)
