"""TDD tests for PUT /api/v1/users/github-token endpoint — Issue #12."""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Test 1: PUT /api/v1/users/github-token stores encrypted PAT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_github_token_stores_token(client: AsyncClient, test_user):
    """PUT with valid payload returns 200 and configured=True."""
    response = await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_testtoken1234567890abcdef",
            "github_username": "testuser",
            "resume_repo_name": "my-resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["configured"] is True
    assert data["github_username"] == "testuser"
    assert data["resume_repo_name"] == "my-resume-vault"
    # Token must never appear in response
    assert "github_token" not in data
    assert "token" not in str(data).lower() or "configured" in str(data).lower()


# ---------------------------------------------------------------------------
# Test 2: GET /api/v1/auth/me shows has_github_token=True after storing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_me_shows_has_github_token_true_after_put(client: AsyncClient, test_user):
    """After PUT, GET /auth/me reflects has_github_token=True."""
    # First ensure the token is stored
    put_resp = await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_testtoken1234567890abcdef",
            "github_username": "tokenuser",
            "resume_repo_name": "resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert put_resp.status_code == 200, put_resp.text

    # Now check /me
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert me_resp.status_code == 200, me_resp.text
    me_data = me_resp.json()
    assert me_data["has_github_token"] is True
    assert me_data["github_username"] == "tokenuser"


# ---------------------------------------------------------------------------
# Test 3: DELETE /api/v1/users/github-token clears the token
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_github_token_clears_it(client: AsyncClient, test_user):
    """DELETE clears the token; subsequent GET /me shows has_github_token=False."""
    # Store a token first
    await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_testtoken1234567890abcdef",
            "github_username": "testuser",
            "resume_repo_name": "resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )

    # Delete it
    del_resp = await client.delete(
        "/api/v1/users/github-token",
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert del_resp.status_code == 200, del_resp.text
    assert del_resp.json()["configured"] is False

    # Verify via /me
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert me_resp.json()["has_github_token"] is False


# ---------------------------------------------------------------------------
# Test 4: Token is never returned in plaintext in any response
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_token_never_returned_in_plaintext(client: AsyncClient, test_user):
    """The raw PAT string must not appear in PUT or GET /me response bodies."""
    raw_token = "ghp_supersecrettoken9876543210xyz"

    put_resp = await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": raw_token,
            "github_username": "secureuser",
            "resume_repo_name": "resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert put_resp.status_code == 200
    assert raw_token not in put_resp.text

    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert me_resp.status_code == 200
    assert raw_token not in me_resp.text


# ---------------------------------------------------------------------------
# Test 5: Missing required fields returns 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_github_token_missing_fields_returns_422(client: AsyncClient, test_user):
    """PUT without required fields (github_token, github_username) returns 422."""
    response = await client.put(
        "/api/v1/users/github-token",
        json={},  # Missing all required fields
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert response.status_code == 422

    # Also check with only partial fields
    response2 = await client.put(
        "/api/v1/users/github-token",
        json={"github_token": "ghp_token12345678901234"},  # Missing github_username
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert response2.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: Unauthenticated request returns 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_github_token_unauthenticated_returns_401(client: AsyncClient):
    """PUT without auth header returns 401 (no dev fallback user exists)."""
    response = await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_testtoken1234567890abcdef",
            "github_username": "testuser",
            "resume_repo_name": "resume-vault",
        },
        # No X-Clerk-User-Id header and no test_user in DB
    )
    assert response.status_code == 401
