from __future__ import annotations

import time

import pytest

from supportsense.resilience import CircuitBreaker, CircuitOpenError, CircuitState
from supportsense.tooling import (
    CircuitOpenToolFailure,
    SupportBackend,
    ToolExecutor,
    TransientToolFailure,
)


class FailingBackend(SupportBackend):
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_name, arguments, idempotency_key, tenant_id):
        self.calls += 1
        raise TransientToolFailure("temporary outage")


class SlowBackend(SupportBackend):
    def execute(self, tool_name, arguments, idempotency_key, tenant_id):
        time.sleep(0.2)
        return {"late": True}


def test_circuit_breaker_opens_and_recovers_with_one_probe() -> None:
    now = [100.0]
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=lambda: now[0],
    )
    breaker.before_call()
    breaker.record_failure()
    breaker.before_call()
    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()

    now[0] += 10
    assert breaker.before_call() == CircuitState.HALF_OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_tool_executor_stops_retrying_when_circuit_opens() -> None:
    backend = FailingBackend()
    executor = ToolExecutor(
        backend,
        max_attempts=5,
        sleep=lambda _: None,
        circuit_breaker=CircuitBreaker(failure_threshold=2),
        dependency_name="test_gateway",
    )

    with pytest.raises(CircuitOpenToolFailure):
        executor._execute_with_resilience("get_customer", {}, "idem", "tenant")

    assert backend.calls == 2


def test_tool_timeout_returns_without_waiting_for_slow_worker() -> None:
    executor = ToolExecutor(
        SlowBackend(),
        timeout_seconds=0.01,
        max_attempts=1,
        circuit_breaker=CircuitBreaker(failure_threshold=10),
        dependency_name="slow_gateway",
    )

    started = time.perf_counter()
    with pytest.raises(TransientToolFailure):
        executor._execute_with_resilience("get_customer", {}, "idem", "tenant")

    assert time.perf_counter() - started < 0.1
