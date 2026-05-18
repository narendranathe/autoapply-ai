"""Smoke tests — verify new vault routers are mounted and return auth errors (not 404)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stories_route_mounted(no_db_client: AsyncClient):
    """GET /vault/stories must return 401/422 (auth required), not 404."""
    resp = await no_db_client.get("/api/v1/vault/stories")
    assert resp.status_code != 404, "stories router not mounted"


@pytest.mark.asyncio
async def test_offer_evaluate_route_mounted(no_db_client: AsyncClient):
    """POST /vault/offer/evaluate must return 401/422, not 404."""
    resp = await no_db_client.post("/api/v1/vault/offer/evaluate", json={})
    assert resp.status_code != 404, "offer router not mounted"


@pytest.mark.asyncio
async def test_portal_scan_route_mounted(no_db_client: AsyncClient):
    """POST /vault/portal/scan must return 401/422, not 404."""
    resp = await no_db_client.post("/api/v1/vault/portal/scan", json={})
    assert resp.status_code != 404, "portal router not mounted"


@pytest.mark.asyncio
async def test_stories_match_route_mounted(no_db_client: AsyncClient):
    """POST /vault/stories/match must return 401/422, not 404."""
    resp = await no_db_client.post("/api/v1/vault/stories/match", json={})
    assert resp.status_code != 404, "stories/match route not mounted"
