import pytest
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from app.db.base import Base
from app.db.deps import get_db
from app.routers import auth as auth_router
from app.routers import backup as backup_router
from app.routers import rooms as rooms_router
from app.routers import messages as messages_router
from app.routers import users as users_router


# In-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Import all models so metadata is populated
    import app.models  # noqa: F401
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)
    
    async with async_session() as session:
        yield session


@pytest.fixture
async def client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with overridden database dependency and no-op lifespan."""
    
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db
    
    # Build a minimal test app without the migration lifespan
    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield
    
    test_app = FastAPI(lifespan=noop_lifespan)
    test_app.include_router(auth_router.router)
    test_app.include_router(rooms_router.router)
    test_app.include_router(messages_router.router)
    test_app.include_router(users_router.router)
    test_app.include_router(backup_router.router)
    test_app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test"
    ) as ac:
        yield ac
