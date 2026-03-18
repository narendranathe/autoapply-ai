"""
Tests for POST /api/v1/reflect — SSE streaming career reflection endpoint.

Red-green-refactor order:
  1. Happy path: profile context streams SSE tokens
  2. Auth required: no credentials → 401
  3. Application context: fetches application from DB and includes in prompt
  4. Missing application_id: 422 when context_type=application with no id
  5. Unknown application_id: 404 when application not found
  6. LLM failure: gateway exception → event:error SSE frame (no crash)
  7. AuditLog: successful call creates AuditLog row with action=reflect_stream
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_llm_gateway
from app.main import create_app
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.llm_gateway import LLMGateway

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def authed_client(
    db_session: AsyncSession, test_user: User
) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client with get_db, get_current_user, and get_llm_gateway overridden.
    Required for routes that call get_current_user (i.e., all authenticated routes).
    """
    app = create_app()

    fake_gateway = MagicMock(spec=LLMGateway)
    fake_gateway.generate = AsyncMock(return_value=(_LONG_RESPONSE, "anthropic"))

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def unauthed_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with get_db overridden but get_current_user NOT overridden (tests 401 paths)."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def test_application(db_session: AsyncSession, test_user: User) -> Application:
    """A single application owned by test_user."""
    app = Application(
        id=uuid.uuid4(),
        user_id=test_user.id,
        company_name="Acme Corp",
        role_title="Senior Engineer",
        job_url="https://acme.com/jobs/1",
        platform="linkedin",
        status="applied",
        jd_hash="a" * 64,
        git_path="applications/acme-senior-engineer-2025/",
    )
    db_session.add(app)
    await db_session.flush()
    await db_session.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_RESPONSE = "This is a detailed career reflection. " * 20  # > 200 chars


def _sse_lines(body: str) -> list[str]:
    """Extract data payloads from a raw SSE body."""
    lines = []
    for line in body.splitlines():
        if line.startswith("data: "):
            lines.append(line[6:])
        elif line.startswith("event: "):
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Test 1: Happy path — profile context streams SSE tokens
# ---------------------------------------------------------------------------


async def test_reflect_profile_streams_sse_tokens(authed_client: AsyncClient):
    """
    POST /api/v1/reflect with context_type=profile returns 200 text/event-stream
    and streams data: lines containing LLM content.
    """
    async with authed_client.stream(
        "POST",
        "/api/v1/reflect",
        json={"context_type": "profile"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = await response.aread()

    sse_data = _sse_lines(body.decode())
    assert len(sse_data) > 0, "Expected at least one SSE data line"
    # Filter out the terminal [DONE] sentinel before reassembling content
    content_tokens = [t for t in sse_data if t != "[DONE]"]
    reassembled = "".join(content_tokens)
    assert reassembled.strip() == _LONG_RESPONSE.strip()


# ---------------------------------------------------------------------------
# Test 2: Invalid context_type → 422
# ---------------------------------------------------------------------------


async def test_reflect_invalid_context_type(authed_client: AsyncClient):
    """POST /api/v1/reflect with an unrecognised context_type → 422 (Pydantic validation)."""
    response = await authed_client.post(
        "/api/v1/reflect",
        json={"context_type": "bogus_type"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 3: [DONE] event at end of successful stream
# ---------------------------------------------------------------------------


async def test_reflect_done_event_at_end(authed_client: AsyncClient):
    """
    The last SSE data frame in a successful stream must be ``data: [DONE]``.
    """
    async with authed_client.stream(
        "POST",
        "/api/v1/reflect",
        json={"context_type": "profile"},
    ) as response:
        assert response.status_code == 200
        body = await response.aread()

    data_lines = [
        line[6:]  # strip "data: " prefix
        for line in body.decode().splitlines()
        if line.startswith("data: ")
    ]
    assert data_lines, "Expected at least one SSE data line"
    assert (
        data_lines[-1] == "[DONE]"
    ), f"Last SSE data line should be [DONE], got: {data_lines[-1]!r}"


# ---------------------------------------------------------------------------
# Test 4: Auth required — no credentials → 401
# ---------------------------------------------------------------------------


async def test_reflect_requires_auth(unauthed_client: AsyncClient):
    """POST /api/v1/reflect with no credentials returns 401."""
    response = await unauthed_client.post(
        "/api/v1/reflect",
        json={"context_type": "profile"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 3: Application context — fetches application and includes in prompt
# ---------------------------------------------------------------------------


async def test_reflect_application_context_builds_prompt_with_company(
    db_session: AsyncSession,
    test_user: User,
    test_application: Application,
):
    """
    POST /api/v1/reflect with context_type=application and a valid application_id
    calls the LLM gateway with a prompt containing the company name and role title.
    """
    app = create_app()

    captured_prompts: list[tuple[str, str]] = []

    async def fake_generate(system_prompt: str, user_prompt: str, **kwargs) -> tuple[str, str]:
        captured_prompts.append((system_prompt, user_prompt))
        return (_LONG_RESPONSE, "anthropic")

    fake_gateway = MagicMock(spec=LLMGateway)
    fake_gateway.generate = AsyncMock(side_effect=fake_generate)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        client.stream(
            "POST",
            "/api/v1/reflect",
            json={"context_type": "application", "application_id": str(test_application.id)},
        ) as response,
    ):
        assert response.status_code == 200
        await response.aread()

    assert len(captured_prompts) == 1
    _, user_prompt = captured_prompts[0]
    assert "Acme Corp" in user_prompt
    assert "Senior Engineer" in user_prompt


# ---------------------------------------------------------------------------
# Test 4: Missing application_id → 422
# ---------------------------------------------------------------------------


async def test_reflect_application_context_without_id_returns_422(authed_client: AsyncClient):
    """POST /api/v1/reflect with context_type=application and no application_id → 422."""
    response = await authed_client.post(
        "/api/v1/reflect",
        json={"context_type": "application"},  # no application_id
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 5: Unknown application_id → 404
# ---------------------------------------------------------------------------


async def test_reflect_unknown_application_id_returns_404(authed_client: AsyncClient):
    """POST /api/v1/reflect with a non-existent application_id → 404."""
    response = await authed_client.post(
        "/api/v1/reflect",
        json={"context_type": "application", "application_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test 6: LLM gateway failure → event:error SSE frame (no 500 crash)
# ---------------------------------------------------------------------------


async def test_reflect_llm_failure_emits_error_sse_frame(db_session: AsyncSession, test_user: User):
    """
    When the LLM gateway raises an exception, the endpoint emits an event:error
    SSE frame and returns 200 (the stream opened successfully; error is in-band).
    """
    app = create_app()

    fake_gateway = MagicMock(spec=LLMGateway)
    fake_gateway.generate = AsyncMock(side_effect=Exception("LLM timeout"))

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        client.stream(
            "POST",
            "/api/v1/reflect",
            json={"context_type": "profile"},
        ) as response,
    ):
        assert response.status_code == 200
        body = await response.aread()

    lines = _sse_lines(body.decode())
    assert any("event: error" in line for line in lines) or any(
        "unavailable" in line.lower() for line in lines
    )


# ---------------------------------------------------------------------------
# Test 7: AuditLog — successful call creates a row with action=reflect_stream
# ---------------------------------------------------------------------------


async def test_reflect_creates_audit_log_entry(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
):
    """A successful reflect call must create an AuditLog row with action=reflect_stream."""
    async with authed_client.stream(
        "POST",
        "/api/v1/reflect",
        json={"context_type": "profile"},
    ) as response:
        assert response.status_code == 200
        await response.aread()

    # Flush so the AuditLog written in the generator's finally block is visible
    await db_session.flush()

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "reflect_stream"))
    log = result.scalar_one_or_none()
    assert log is not None, "AuditLog row with action=reflect_stream was not created"
    assert log.user_hash == str(test_user.id)
    assert log.success is True
