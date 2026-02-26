"""
Alembic environment configuration.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.config import settings
from app.models import Base

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use settings.DATABASE_URL directly — bypasses configparser which misinterprets
# percent-encoded characters (e.g. %40 in passwords) as interpolation syntax.
_DATABASE_URL = settings.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    _connect_args: dict = {}
    if settings.DB_SSL_REQUIRE:
        _connect_args["ssl"] = "require"
    if settings.DB_PASSWORD:
        _connect_args["password"] = settings.DB_PASSWORD

    connectable = create_async_engine(
        _DATABASE_URL,
        pool_pre_ping=True,
        connect_args=_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
