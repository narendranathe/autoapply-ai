"""
Test fixtures - WORKING VERSION (No session-scoped DB fixtures)
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import get_db
from app.main import create_app
from app.models.base import Base

TEST_DB_URL = "postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Create tables once for all tests."""
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup after all tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session():
    """
    Fresh connection and transaction per test.
    Automatically rolls back after each test.
    """
    # Create fresh engine for each test to avoid connection sharing issues
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool, echo=False)

    async with engine.connect() as conn:
        # Begin transaction
        trans = await conn.begin()

        # Create session bound to this connection
        session_maker = async_sessionmaker(bind=conn, expire_on_commit=False, class_=AsyncSession)
        session = session_maker()

        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession):
    """HTTP test client with overridden DB dependency."""
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
