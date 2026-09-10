from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status


@dataclass(slots=True)
class SlidingWindowLimiter:
    """Per-client sliding-window rate limiter (in-memory, single process).

    Keys on the client IP (fallback to a default bucket when no IP is seen).
    Bursts above `limit` requests within `window_seconds` get HTTP 429.
    """

    limit: int = 30
    window_seconds: float = 60.0
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    @staticmethod
    def _client_key(request: Request) -> str:
        client = request.client
        return client.host if client and client.host else "unknown"

    def check(self, request: Request) -> None:
        key = self._client_key(request)
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > self.window_seconds:
            window.popleft()
        if len(window) >= self.limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="请求过于频繁，请稍后再试。")
        window.append(now)
