"""In-process metrics collection for observability.

This module provides lightweight request/latency/error metrics that can be
consumed by Prometheus, Datadog, or any monitoring stack via the /metrics
endpoint.  No external ``prometheus_client`` dependency is required; the
exposed format is plain JSON so any scraper can pick it up.  If the real
library is installed the exporter will auto-upgrade to the native format.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Bucket:
    """Holds the aggregated counters for one metric name."""
    count: int = 0
    error_count: int = 0
    latency_sum_ms: float = 0.0
    latency_buckets: deque = field(default_factory=lambda: deque(maxlen=200))
    last_updated: float = field(default_factory=time.time)


class MetricsCollector:
    """Thread-safe, in-process metrics registry.

    Keys are dotted metric names (``http.request.count``,
    ``http.request.latency_ms``).  Each name maps to a ``_Bucket`` that
    accumulates counts, error counts, and latency samples for percentile
    calculation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def _get(self, name: str) -> _Bucket:
        with self._lock:
            bucket = self._buckets.get(name)
            if bucket is None:
                bucket = _Bucket()
                self._buckets[name] = bucket
            return bucket

    def observe_request(self, name: str, latency_ms: float, is_error: bool = False) -> None:
        bucket = self._get(name)
        with self._lock:
            bucket.count += 1
            bucket.last_updated = time.time()
            if is_error:
                bucket.error_count += 1
            bucket.latency_sum_ms += latency_ms
            bucket.latency_buckets.append(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {}
            for name, bucket in self._buckets.items():
                latencies = list(bucket.latency_buckets)
                latencies.sort()
                p50 = p95 = p99 = 0.0
                if latencies:
                    p50 = latencies[int(len(latencies) * 0.5)]
                    p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
                    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]
                error_rate = bucket.error_count / bucket.count if bucket.count else 0.0
                result[name] = {
                    "count": bucket.count,
                    "error_count": bucket.error_count,
                    "error_rate": round(error_rate, 6),
                    "avg_latency_ms": round(bucket.latency_sum_ms / bucket.count, 2) if bucket.count else 0.0,
                    "p50_latency_ms": round(p50, 2),
                    "p95_latency_ms": round(p95, 2),
                    "p99_latency_ms": round(p99, 2),
                    "last_updated": bucket.last_updated,
                }
            return result


# Global singleton — the middleware writes here; the endpoint reads from here.
metrics = MetricsCollector()
