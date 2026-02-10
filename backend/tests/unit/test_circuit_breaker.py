"""
Tests for circuit breaker pattern.
"""

import pytest

from app.middleware.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


@pytest.fixture
def breaker():
    return CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=1)


class TestCircuitBreaker:
    def test_starts_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker):
        @breaker
        async def fail():
            raise ConnectionError("service down")

        with pytest.raises(ConnectionError):
            await fail()
        with pytest.raises(ConnectionError):
            await fail()

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self, breaker):
        @breaker
        async def fail():
            raise ConnectionError("service down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await fail()

        with pytest.raises(CircuitOpenError):
            await fail()
