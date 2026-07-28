from __future__ import annotations

import threading
import time
from enum import StrEnum
from typing import Callable


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a dependency call is rejected by an open circuit."""


class CircuitBreaker:
    """Thread-safe circuit breaker with a single half-open probe."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_progress = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._opened_at is not None
                and self.clock() - self._opened_at >= self.recovery_timeout_seconds
            ):
                return CircuitState.HALF_OPEN
            return self._state

    def before_call(self) -> CircuitState:
        with self._lock:
            now = self.clock()
            if self._state == CircuitState.OPEN:
                if (
                    self._opened_at is None
                    or now - self._opened_at < self.recovery_timeout_seconds
                ):
                    raise CircuitOpenError("Dependency circuit is open")
                self._state = CircuitState.HALF_OPEN
            if self._state == CircuitState.HALF_OPEN:
                if self._probe_in_progress:
                    raise CircuitOpenError("Dependency circuit probe is in progress")
                self._probe_in_progress = True
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_progress = False

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == CircuitState.HALF_OPEN
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self.clock()
            self._probe_in_progress = False

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            state = self._state
            if (
                state == CircuitState.OPEN
                and self._opened_at is not None
                and self.clock() - self._opened_at >= self.recovery_timeout_seconds
            ):
                state = CircuitState.HALF_OPEN
            return {
                "state": state.value,
                "consecutive_failures": self._consecutive_failures,
                "opened_at": self._opened_at,
            }
