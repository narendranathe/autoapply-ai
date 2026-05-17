"""
Tests for health check endpoints.
"""

from unittest.mock import AsyncMock

import pytest

from app.dependencies import get_db, get_redis


@pytest.mark.asyncio
async def test_health_returns_ok_when_db_and_redis_healthy(client):
    fake_redis = AsyncMock()
    fake_redis.ping.return_value = True
    client._transport.app.dependency_overrides[get_redis] = lambda: fake_redis

    try:
        response = await client.get("/health")
    finally:
        client._transport.app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


@pytest.mark.asyncio
async def test_health_has_request_id_header(client):
    fake_redis = AsyncMock()
    fake_redis.ping.return_value = True
    client._transport.app.dependency_overrides[get_redis] = lambda: fake_redis

    try:
        response = await client.get("/health")
    finally:
        client._transport.app.dependency_overrides.pop(get_redis, None)

    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_health_returns_503_when_db_down(client):
    failing_db = AsyncMock()
    failing_db.execute.side_effect = RuntimeError("connection refused")
    fake_redis = AsyncMock()
    fake_redis.ping.return_value = True

    async def override_get_db():
        yield failing_db

    app = client._transport.app
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = lambda: fake_redis

    try:
        response = await client.get("/health")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db"].startswith("error:")
    assert "connection refused" in data["db"]
    assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_503_when_redis_down(client):
    failing_redis = AsyncMock()
    failing_redis.ping.side_effect = RuntimeError("redis unreachable")
    client._transport.app.dependency_overrides[get_redis] = lambda: failing_redis

    try:
        response = await client.get("/health")
    finally:
        client._transport.app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db"] == "ok"
    assert data["redis"].startswith("error:")
    assert "redis unreachable" in data["redis"]


@pytest.mark.asyncio
async def test_ready_checks_dependencies(client):
    response = await client.get("/ready")
    data = response.json()
    assert "checks" in data
    assert "database" in data["checks"]
