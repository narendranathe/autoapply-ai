"""
Test fixtures with proper async SQLAlchemy isolation.
Fixes: 'operation in progress', 'different loop', and foreign key issues.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import get_db
from app.main import create_app
from app.models.base import Base
from app.models.user import User

# Use the test database (port 5433 from docker-compose)
TEST_DB_URL = "postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the entire test session (Windows compatible)."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        poolclass=None,  # Disable pooling to prevent "operation in progress" errors
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session with full isolation per test.
    Creates tables → runs test → rolls back → drops tables.
    """
    # Clean slate: drop any tables left by alembic or a prior run, then recreate
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory bound to the engine
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
    )

    # Create session and transaction
    async with async_session() as session:  # noqa: SIM117
        async with session.begin():
            try:
                yield session
            finally:
                await session.rollback()

    # Clean up: drop all tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP test client with database dependency overridden.
    """
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """
    Create a test user in the database.
    Required for Application tests (foreign key constraint).
    """
    user = User(
        id=uuid.uuid4(),
        clerk_id=f"test_clerk_{uuid.uuid4().hex[:8]}",
        email_hash="a" * 64,  # Fake SHA-256 hash
        github_username="testuser",
        resume_repo_name="resume-vault",
        is_active=True,
        total_resumes_generated=0,
        total_applications_tracked=0,
    )
    db_session.add(user)
    await db_session.flush()  # Get the ID without committing
    await db_session.refresh(user)
    return user
