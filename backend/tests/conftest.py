import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models.base import Base
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get database URL from environment
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", 
    "postgresql+asyncpg://autoapply:testpassword@localhost:5432/autoapply_test"
)

@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create test engine using PostgreSQL."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    """Create a test session."""
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
