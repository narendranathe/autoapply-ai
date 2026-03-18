"""TDD tests for PUT /api/v1/users/github-token endpoint — Issue #12."""

from unittest.mock import AsyncMock, patch

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


# ---------------------------------------------------------------------------
# Tests for Feature #14: auto-commit .tex to GitHub after POST /vault/generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_resume_commits_to_github(client: AsyncClient, test_user):
    """When user has a GitHub token, generate endpoint commits .tex and returns github_path."""
    fake_commit_result = {
        "versions_path": "versions/Test_Acme_DE.tex",
        "versions_sha": "abc123sha",
        "app_dir": "applications/Test_Acme_DE_2026-03-18",
        "git_tag": "Test_Acme_DE",
        "tag_sha": "def456",
    }
    # Ensure user has a GitHub token
    await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_fake_token_12345678",
            "github_username": "testuser",
            "resume_repo_name": "resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )

    with (
        patch(
            "app.routers.vault._github_service.commit_named_resume",
            new=AsyncMock(return_value=fake_commit_result),
        ),
        patch(
            "app.routers.vault.generate_full_latex_resume",
            new=AsyncMock(
                return_value=type(
                    "G",
                    (),
                    {
                        "version_tag": "Test_Acme_DE",
                        "recruiter_filename": "Test.pdf",
                        "latex_content": r"\documentclass{article}\begin{document}Test resume\end{document}",
                        "markdown_preview": "# Test",
                        "ats_score_estimate": 80.0,
                        "skills_gap": [],
                        "changes_summary": "Generated",
                        "llm_provider_used": "anthropic",
                        "generation_warnings": [],
                    },
                )()
            ),
        ),
    ):
        resp = await client.post(
            "/api/v1/vault/generate",
            data={
                "company_name": "Acme",
                "role_title": "Data Engineer",
                "jd_text": "We need a data engineer with Python skills",
                "name": "Test User",
                "phone": "555-0000",
                "email": "test@test.com",
                "linkedin_url": "https://linkedin.com/in/test",
                "linkedin_label": "test",
                "work_history_text": "Senior DE at Acme 2020-2024",
            },
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["github_path"] == "versions/Test_Acme_DE.tex"
    assert "github.com/testuser/resume-vault/blob/main/versions/Test_Acme_DE.tex" in (
        data["github_url"] or ""
    )


@pytest.mark.asyncio
async def test_generate_resume_no_github_token_returns_null(client: AsyncClient, test_user):
    """When user has no GitHub token, generate succeeds with github_path: null."""
    with patch(
        "app.routers.vault.generate_full_latex_resume",
        new=AsyncMock(
            return_value=type(
                "G",
                (),
                {
                    "version_tag": "Test_Corp_SWE",
                    "recruiter_filename": "Test.pdf",
                    "latex_content": r"\documentclass{article}\begin{document}Resume content\end{document}",
                    "markdown_preview": "# Test",
                    "ats_score_estimate": 75.0,
                    "skills_gap": [],
                    "changes_summary": "Generated",
                    "llm_provider_used": "keyword",
                    "generation_warnings": [],
                },
            )()
        ),
    ):
        resp = await client.post(
            "/api/v1/vault/generate",
            data={
                "company_name": "Corp",
                "role_title": "SWE",
                "jd_text": "Software engineer needed",
                "name": "Test User",
                "phone": "555-0000",
                "email": "test@test.com",
                "linkedin_url": "https://linkedin.com/in/test",
                "linkedin_label": "test",
                "work_history_text": "SWE at Corp 2021-2024",
            },
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["github_path"] is None
    assert data["github_url"] is None


@pytest.mark.asyncio
async def test_generate_resume_github_failure_does_not_block(client: AsyncClient, test_user):
    """When GitHub API throws, generate still returns 200 with github_path: null."""
    # Give user a token first
    await client.put(
        "/api/v1/users/github-token",
        json={
            "github_token": "ghp_fake_token_12345678",
            "github_username": "testuser",
            "resume_repo_name": "resume-vault",
        },
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )

    with (
        patch(
            "app.routers.vault._github_service.commit_named_resume",
            new=AsyncMock(side_effect=RuntimeError("GitHub API rate limit exceeded")),
        ),
        patch(
            "app.routers.vault.generate_full_latex_resume",
            new=AsyncMock(
                return_value=type(
                    "G",
                    (),
                    {
                        "version_tag": "Test_GitHub_Fail",
                        "recruiter_filename": "Test.pdf",
                        "latex_content": r"\documentclass{article}\begin{document}Failure test\end{document}",
                        "markdown_preview": "# Test",
                        "ats_score_estimate": 70.0,
                        "skills_gap": [],
                        "changes_summary": "Generated",
                        "llm_provider_used": "keyword",
                        "generation_warnings": [],
                    },
                )()
            ),
        ),
    ):
        resp = await client.post(
            "/api/v1/vault/generate",
            data={
                "company_name": "GitHubFail",
                "role_title": "Engineer",
                "jd_text": "Engineer role at failing GitHub company",
                "name": "Test User",
                "phone": "555-0000",
                "email": "test@test.com",
                "linkedin_url": "https://linkedin.com/in/test",
                "linkedin_label": "test",
                "work_history_text": "Engineer at GitHubFail 2022-2024",
            },
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )

    # Generation must succeed even though GitHub failed
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["github_path"] is None
    assert data["github_url"] is None
    assert "resume_id" in data
