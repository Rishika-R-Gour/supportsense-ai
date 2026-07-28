from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from threading import Lock

from supportsense.config import settings


class RateLimiter:
    def check(self, key: str) -> tuple[bool, int]:
        raise NotImplementedError

    def ready(self) -> bool:
        return True


class InMemoryRateLimiter(RateLimiter):
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        self._lock = Lock()

    def check(self, key: str) -> tuple[bool, int]:
        window = int(time.time() // self.window_seconds)
        with self._lock:
            bucket_window, count = self._buckets[key]
            count = count + 1 if bucket_window == window else 1
            self._buckets[key] = (window, count)
        return count <= self.limit, max(0, self.limit - count)


class RedisRateLimiter(RateLimiter):
    def __init__(self, url: str, limit: int, window_seconds: int = 60) -> None:
        import redis

        self.client = redis.Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, key: str) -> tuple[bool, int]:
        window = int(time.time() // self.window_seconds)
        redis_key = f"rate:{window}:{key}"
        with self.client.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.window_seconds + 2)
            count, _ = pipe.execute()
        return int(count) <= self.limit, max(0, self.limit - int(count))

    def ready(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False


def request_identity(authorization: str | None, client_host: str | None) -> str:
    raw = authorization or client_host or "anonymous"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


rate_limiter: RateLimiter = (
    RedisRateLimiter(settings.redis_url, settings.rate_limit_per_minute)
    if settings.redis_url
    else InMemoryRateLimiter(settings.rate_limit_per_minute)
)
