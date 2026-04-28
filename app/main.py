import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI


async def run_migrations() -> None:
    """Apply all pending Alembic migrations before the app starts (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    yield


app = FastAPI(title="Telecommunicator", lifespan=lifespan)

from app.routers import auth as auth_router  # noqa: E402
from app.routers import backup as backup_router  # noqa: E402
from app.routers import messages as messages_router  # noqa: E402
from app.routers import rooms as rooms_router  # noqa: E402
from app.routers import users as users_router  # noqa: E402
from app.routers import ws as ws_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(rooms_router.router)
app.include_router(messages_router.router)
app.include_router(users_router.router)
app.include_router(ws_router.router)
app.include_router(backup_router.router)
