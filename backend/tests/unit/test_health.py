"""
Tests for health check endpoints.
"""

import pytest


@pytest.mark.asyncio
async def test_health_returns_alive(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_health_has_request_id_header(client):
    response = await client.get("/health")
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_ready_checks_dependencies(client):
    response = await client.get("/ready")
    data = response.json()
    assert "checks" in data
    assert "database" in data["checks"]
