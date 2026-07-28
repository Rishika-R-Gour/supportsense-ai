from __future__ import annotations

from supportsense.rate_limit import InMemoryRateLimiter, request_identity


def test_fixed_window_rate_limit_and_private_identity() -> None:
    limiter = InMemoryRateLimiter(limit=2, window_seconds=3600)
    key = request_identity("Bearer secret-token", None)

    assert key != "Bearer secret-token"
    assert limiter.check(key) == (True, 1)
    assert limiter.check(key) == (True, 0)
    assert limiter.check(key) == (False, 0)
