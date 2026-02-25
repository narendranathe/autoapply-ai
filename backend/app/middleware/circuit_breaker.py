"""
Circuit breaker for external service calls.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, name: str, retry_after_seconds: int):
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit '{name}' is OPEN. Retry after {retry_after_seconds}s.")


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = timedelta(seconds=recovery_timeout)
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = datetime.utcnow() - self._last_failure_time
            if elapsed > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def _on_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count += 1

    def _on_failure(self, error: Exception) -> None:
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_state = self.state
            if current_state == CircuitState.OPEN:
                remaining = 0
                if self._last_failure_time:
                    elapsed = datetime.utcnow() - self._last_failure_time
                    remaining = max(
                        0, int(self.recovery_timeout.total_seconds() - elapsed.total_seconds())
                    )
                raise CircuitOpenError(self.name, remaining)

            if current_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls > self.half_open_max_calls:
                    raise CircuitOpenError(self.name, 10)

            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result
            except CircuitOpenError:
                raise
            except Exception as e:
                self._on_failure(e)
                raise

        wrapper.circuit = self  # type: ignore[attr-defined]
        return wrapper

    def get_metrics(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
        }


github_circuit = CircuitBreaker(name="github_api", failure_threshold=3, recovery_timeout=60)
llm_circuit = CircuitBreaker(name="llm_provider", failure_threshold=2, recovery_timeout=30)
pdf_circuit = CircuitBreaker(name="pdf_service", failure_threshold=3, recovery_timeout=120)
