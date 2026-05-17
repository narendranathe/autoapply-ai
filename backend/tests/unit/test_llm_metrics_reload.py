"""Regression test for Prometheus duplicate registration on module reload.

Issue #185 — The previous implementation wrapped collector construction
in a bare ``except Exception``. On ``importlib.reload(llm_gateway)`` (or
uvicorn ``--reload``) ``prometheus_client`` raises
``ValueError: Duplicated timeseries`` because the default ``REGISTRY``
already contains the collector. The bare-except silently flipped
``_HAS_PROMETHEUS`` to ``False`` and left the module's collector
references as ``None`` for the rest of the process, killing metrics.

We test by running ``importlib.reload`` inside a subprocess so module
identity in the host test process is unaffected, and by exercising the
helper functions directly in-process.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from app.services import llm_gateway


@pytest.mark.skipif(not llm_gateway._HAS_PROMETHEUS, reason="prometheus_client unavailable")
def test_reload_keeps_prometheus_enabled_in_subprocess():
    """After importlib.reload, _HAS_PROMETHEUS stays True and collectors
    remain usable (i.e. .labels(...).inc() doesn't raise).

    Runs in a subprocess so the reload doesn't replace classes that other
    tests in this process import directly (e.g. ``LLMGenerationError``).
    """
    script = textwrap.dedent("""
        import importlib
        import sys

        from app.services import llm_gateway

        assert llm_gateway._HAS_PROMETHEUS is True, "metrics disabled on first import"

        # Simulate uvicorn --reload / importlib.reload
        reloaded = importlib.reload(llm_gateway)

        assert reloaded._HAS_PROMETHEUS is True, "metrics disabled after reload"
        assert reloaded._llm_request_total is not None
        assert reloaded._llm_request_duration_seconds is not None

        # Exercise the recovered collectors — must not raise.
        reloaded._llm_request_total.labels(provider="anthropic", status="success").inc()
        reloaded._llm_request_duration_seconds.labels(provider="anthropic").observe(0.42)

        # _emit_metric still works after reload.
        reloaded._emit_metric("openai", "success", 12.3)
        reloaded._emit_metric("openai", "failure", 5.0)

        print("OK")
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"subprocess failed:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    assert "OK" in result.stdout


@pytest.mark.skipif(not llm_gateway._HAS_PROMETHEUS, reason="prometheus_client unavailable")
def test_helper_recovers_existing_collector_on_value_error():
    """The helper must return the already-registered collector when
    ``Counter()`` raises ``ValueError`` for a duplicate name.
    """
    # First call: registers under a unique name.
    name = "llm_test_duplicate_counter_xyz"
    first = llm_gateway._get_or_create_counter(name, "doc", ("p",))
    # Second call with the same name: must return the same object (not raise).
    second = llm_gateway._get_or_create_counter(name, "doc", ("p",))
    assert first is second


@pytest.mark.skipif(not llm_gateway._HAS_PROMETHEUS, reason="prometheus_client unavailable")
def test_helper_recovers_existing_histogram_on_value_error():
    name = "llm_test_duplicate_histogram_xyz"
    first = llm_gateway._get_or_create_histogram(name, "doc", ("p",), (1.0, 2.0, float("inf")))
    second = llm_gateway._get_or_create_histogram(name, "doc", ("p",), (1.0, 2.0, float("inf")))
    assert first is second


def test_histogram_has_llm_latency_buckets():
    """Issue #185 — histogram must use the explicit LLM-latency bucket set
    so 60s/120s/180s Ollama timeouts are observable.
    """
    if not llm_gateway._HAS_PROMETHEUS:
        pytest.skip("prometheus_client unavailable")

    histogram = llm_gateway._llm_request_duration_seconds
    assert histogram is not None
    # Touch a labelset so .collect() exposes the bucket boundaries.
    histogram.labels(provider="_bucket_probe").observe(0.0)
    upper_bounds: list[float] = []
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name.endswith("_bucket"):
                le = sample.labels.get("le")
                if le is not None:
                    upper_bounds.append(float(le))
    # The buckets we expect to be present
    expected_in = {60.0, 120.0, 180.0}
    assert expected_in.issubset(set(upper_bounds)), (
        f"missing LLM latency buckets {expected_in - set(upper_bounds)} "
        f"from configured set {sorted(set(upper_bounds))}"
    )
