"""Regression tests for the Redis breaker covering ``tailor_resume``.

Issue #189 — ``tailor_resume`` calls ``provider.complete()`` directly on
the ``PROVIDERS`` registry instance. Before this fix it was gated only
by the legacy in-process ``@llm_circuit`` decorator and bypassed the new
Redis breaker entirely. The fix wraps the call site with
``llm_circuit_redis.is_open`` (pre-check) and
``record_success`` / ``record_failure`` (post-check) so the highest-
volume LLM caller participates in the new breaker.

We construct a minimal ``ResumeAST`` and patch the provider's
``complete()`` so the test stays in-process.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import llm_circuit_redis, llm_gateway
from app.services.llm_gateway import (
    PROVIDERS,
    RewriteStrategy,
    tailor_resume,
)
from app.services.resume_parser import ResumeAST, ResumeBullet, ResumeSection


def _make_ast() -> ResumeAST:
    return ResumeAST(
        bullets=[
            ResumeBullet(
                text="Built a thing",
                section=ResumeSection.EXPERIENCE,
                company="ACME",
                role="Engineer",
                dates="2020-2024",
                original_index=0,
            ),
            ResumeBullet(
                text="Did another thing",
                section=ResumeSection.EXPERIENCE,
                company="ACME",
                role="Engineer",
                dates="2020-2024",
                original_index=1,
            ),
        ],
        raw_text="resume",
    )


@pytest.mark.asyncio
async def test_tailor_resume_short_circuits_when_redis_breaker_open():
    """If is_open('anthropic') returns True, provider.complete must NOT be
    called and the function must return the fallback summary.
    """
    ast = _make_ast()
    anthropic = PROVIDERS["anthropic"]
    complete_mock = AsyncMock(return_value="rewritten line 1\nrewritten line 2")

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(side_effect=lambda name, client=None: name == "anthropic"),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch("app.services.llm_gateway.decrypt_value", return_value="sk-ant-fake-key-123456"),
        patch.object(anthropic, "complete", new=complete_mock),
    ):
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=ast,
            job_description="JD text",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="encrypted",
        )

    complete_mock.assert_not_awaited()
    assert used_fallback is True
    assert "circuit open" in summary.lower()
    # Falls back to original bullets — count and content preserved.
    assert len(bullets) == 2
    assert bullets[0] == "Built a thing"


@pytest.mark.asyncio
async def test_tailor_resume_records_success_on_provider_success():
    """A successful provider call must call ``record_success`` on the
    Redis breaker so the failure counter resets.
    """
    ast = _make_ast()
    anthropic = PROVIDERS["anthropic"]
    complete_mock = AsyncMock(return_value="rewritten line 1\nrewritten line 2")
    success_mock = AsyncMock(return_value=None)

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch("app.services.llm_circuit_redis.record_success", new=success_mock),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch("app.services.llm_gateway.decrypt_value", return_value="sk-ant-fake-key-123456"),
        patch.object(anthropic, "complete", new=complete_mock),
    ):
        _, used_fallback, _ = await tailor_resume(
            resume_ast=ast,
            job_description="JD",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="encrypted",
        )

    assert used_fallback is False
    success_mock.assert_awaited()


@pytest.mark.asyncio
async def test_tailor_resume_records_failure_on_provider_exception():
    """A generic provider failure must call ``record_failure`` so three
    such failures will trip the Redis breaker.
    """
    ast = _make_ast()
    anthropic = PROVIDERS["anthropic"]
    complete_mock = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    failure_mock = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.llm_circuit_redis.record_failure", new=failure_mock),
        patch("app.services.llm_gateway.decrypt_value", return_value="sk-ant-fake-key-123456"),
        patch.object(anthropic, "complete", new=complete_mock),
    ):
        _, used_fallback, _ = await tailor_resume(
            resume_ast=ast,
            job_description="JD",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="encrypted",
        )

    assert used_fallback is True
    failure_mock.assert_awaited()


@pytest.mark.asyncio
async def test_tailor_resume_does_not_record_failure_on_invalid_key():
    """``InvalidAPIKeyError`` is a misconfiguration signal, not a provider
    health signal. We must NOT count it as a circuit-breaker failure.
    """
    from app.services.llm_gateway import InvalidAPIKeyError

    ast = _make_ast()
    anthropic = PROVIDERS["anthropic"]
    complete_mock = AsyncMock(side_effect=InvalidAPIKeyError("bad key"))
    failure_mock = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.llm_circuit_redis.record_failure", new=failure_mock),
        patch("app.services.llm_gateway.decrypt_value", return_value="sk-ant-fake-key-123456"),
        patch.object(anthropic, "complete", new=complete_mock),
    ):
        _, used_fallback, summary = await tailor_resume(
            resume_ast=ast,
            job_description="JD",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="encrypted",
        )

    assert used_fallback is True
    assert "invalid" in summary.lower()
    failure_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_tailor_resume_three_failures_open_breaker_end_to_end():
    """Three consecutive provider failures must trip the Redis breaker so
    the fourth call short-circuits before reaching ``provider.complete``.
    Uses the in-memory fake Redis from the circuit-breaker test file.
    """
    from tests.unit.test_llm_gateway_circuit_breaker import _FakeRedis

    fake = _FakeRedis()
    ast = _make_ast()
    anthropic = PROVIDERS["anthropic"]
    complete_mock = AsyncMock(side_effect=RuntimeError("upstream timeout"))

    async def fake_get_client(redis_url=None):  # noqa: ANN001
        return fake

    with (
        patch("app.services.llm_circuit_redis._get_client", new=fake_get_client),
        patch("app.services.llm_gateway.decrypt_value", return_value="sk-ant-fake-key-123456"),
        patch.object(anthropic, "complete", new=complete_mock),
    ):
        # First three calls fail and increment the Redis counter.
        for _ in range(3):
            _, used_fallback, _ = await tailor_resume(
                resume_ast=ast,
                job_description="JD",
                strategy=RewriteStrategy.MODERATE,
                provider_name="anthropic",
                encrypted_api_key="encrypted",
            )
            assert used_fallback is True

        # The circuit must now be open per the Redis state.
        assert await llm_circuit_redis.is_open("anthropic", client=fake) is True

        # Fourth call: provider.complete should NOT be invoked. Reset the mock
        # call count to make that assertion crisp.
        complete_mock.reset_mock()
        _, used_fallback, summary = await tailor_resume(
            resume_ast=ast,
            job_description="JD",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="encrypted",
        )
        assert used_fallback is True
        assert "circuit open" in summary.lower()
        complete_mock.assert_not_awaited()


def test_llm_gateway_module_imports_clean():
    """Quick sanity check that no helper is shadowed by the new code path."""
    assert callable(llm_gateway.tailor_resume)
    assert callable(llm_gateway._scrub)
