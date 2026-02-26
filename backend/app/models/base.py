"""
SQLAlchemy async engine and base model.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

_db_url = make_url(settings.DATABASE_URL)
if settings.DB_PASSWORD:
    _db_url = _db_url.set(password=settings.DB_PASSWORD)

engine = create_async_engine(
    _db_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"ssl": "require"} if settings.DB_SSL_REQUIRE else {},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    """Base for all database models."""

    pass


class TimestampMixin:
    """Adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
