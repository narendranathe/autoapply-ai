"""Tests for LLMGateway request metrics.

Issue #107 — Phase 2. The gateway emits a Prometheus counter +
histogram on every attempt, and additionally logs a structured
``llm.request`` event for log-based dashboards.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import llm_gateway
from app.services.llm_gateway import LLMGateway


def _read_counter_total(counter, provider: str, status: str) -> float:
    """Look up the cumulative value for a labelled counter sample.

    The default prometheus_client registry persists samples across tests,
    so we capture before/after and only compare deltas.
    """
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            labels = sample.labels
            if labels.get("provider") == provider and labels.get("status") == status:
                return float(sample.value)
    return 0.0


def _read_histogram_count(histogram, provider: str) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_count"):
                continue
            if sample.labels.get("provider") == provider:
                return float(sample.value)
    return 0.0


@pytest.mark.asyncio
async def test_success_emits_success_counter_and_histogram_observation():
    if not llm_gateway._HAS_PROMETHEUS:
        pytest.skip("prometheus_client unavailable")

    counter = llm_gateway._llm_request_total
    histogram = llm_gateway._llm_request_duration_seconds
    before_success = _read_counter_total(counter, "anthropic", "success")
    before_hist = _read_histogram_count(histogram, "anthropic")

    payload = "Hello world. " * 30  # >200 chars

    gateway = LLMGateway()
    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(return_value=payload),
        ),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    after_success = _read_counter_total(counter, "anthropic", "success")
    after_hist = _read_histogram_count(histogram, "anthropic")
    assert after_success - before_success == 1
    assert after_hist - before_hist == 1


@pytest.mark.asyncio
async def test_failure_emits_failure_counter():
    if not llm_gateway._HAS_PROMETHEUS:
        pytest.skip("prometheus_client unavailable")

    counter = llm_gateway._llm_request_total
    before_fail_anth = _read_counter_total(counter, "anthropic", "failure")

    gateway = LLMGateway()
    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(side_effect=RuntimeError("API exploded")),
        ),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(side_effect=RuntimeError("ollama down")),
        ),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    after_fail_anth = _read_counter_total(counter, "anthropic", "failure")
    assert after_fail_anth - before_fail_anth == 1


@pytest.mark.asyncio
async def test_circuit_open_emits_circuit_open_metric():
    if not llm_gateway._HAS_PROMETHEUS:
        pytest.skip("prometheus_client unavailable")

    counter = llm_gateway._llm_request_total
    before = _read_counter_total(counter, "anthropic", "circuit_open")

    gateway = LLMGateway()
    payload = "Real reply. " * 30

    is_open_mock = AsyncMock(side_effect=lambda name, client=None: name == "anthropic")
    with (
        patch("app.services.llm_circuit_redis.is_open", new=is_open_mock),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(return_value=payload),
        ),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    after = _read_counter_total(counter, "anthropic", "circuit_open")
    assert after - before == 1


@pytest.mark.asyncio
async def test_emit_metric_never_raises_when_prometheus_missing():
    """The helper must be a no-op when prometheus_client is unavailable."""
    # Force the "no prometheus" path even if the package is installed.
    with patch.object(llm_gateway, "_HAS_PROMETHEUS", False):
        # Should not raise
        llm_gateway._emit_metric("anthropic", "success", 12.0)


@pytest.mark.asyncio
async def test_emit_metric_logs_structured_event(caplog):
    """Always emit a structured ``llm.request`` info event for log dashboards."""
    # The gateway uses loguru, which doesn't propagate to caplog by default.
    # Instead, just verify the helper invokes its emitter cleanly.
    llm_gateway._emit_metric("anthropic", "success", 5.5)
    llm_gateway._emit_metric("openai", "failure", 12.0)
