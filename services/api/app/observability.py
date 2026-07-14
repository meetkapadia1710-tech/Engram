"""In-process metrics: counters + latency histograms, Prometheus exposition.

Process-local by design (each instance exposes its own /metrics; Prometheus
aggregates across replicas). No dependency on a metrics library — the
exposition format is three lines per series.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, float] = defaultdict(float)
# histogram: name -> list of bucket upper bounds; counts per bucket + sum/count
_HIST_BUCKETS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
_hist_counts: dict[str, list[int]] = {}
_hist_sum: dict[str, float] = defaultdict(float)
_hist_n: dict[str, int] = defaultdict(int)

_started_at = time.time()


def count(name: str, value: float = 1.0) -> None:
    with _lock:
        _counters[name] += value


def observe_ms(name: str, ms: float) -> None:
    with _lock:
        buckets = _hist_counts.setdefault(name, [0] * (len(_HIST_BUCKETS) + 1))
        for i, ub in enumerate(_HIST_BUCKETS):
            if ms <= ub:
                buckets[i] += 1
                break
        else:
            buckets[-1] += 1
        _hist_sum[name] += ms
        _hist_n[name] += 1


class timed:
    """Context manager: `with timed("search"): ...` records latency."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        observe_ms(self.name, (time.perf_counter() - self.start) * 1000)
        return False


def _sanitize(name: str) -> str:
    return "engram_" + name.replace(".", "_").replace("-", "_")


def snapshot() -> dict:
    """JSON view for the dashboard."""
    with _lock:
        histograms = {}
        for name, n in _hist_n.items():
            histograms[name] = {
                "count": n,
                "avg_ms": round(_hist_sum[name] / n, 2) if n else 0.0,
                "p95_ms": _percentile(name, 0.95),
            }
        return {
            "uptime_s": round(time.time() - _started_at, 1),
            "counters": dict(sorted(_counters.items())),
            "latency": histograms,
        }


def _percentile(name: str, q: float) -> float:
    buckets = _hist_counts.get(name)
    n = _hist_n.get(name, 0)
    if not buckets or not n:
        return 0.0
    target = q * n
    seen = 0
    for i, c in enumerate(buckets):
        seen += c
        if seen >= target:
            return float(_HIST_BUCKETS[i]) if i < len(_HIST_BUCKETS) else float("inf")
    return float(_HIST_BUCKETS[-1])


def prometheus() -> str:
    """Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        for name, v in sorted(_counters.items()):
            m = _sanitize(name) + "_total"
            lines.append(f"# TYPE {m} counter")
            lines.append(f"{m} {v}")
        for name, buckets in _hist_counts.items():
            m = _sanitize(name) + "_ms"
            lines.append(f"# TYPE {m} histogram")
            cumulative = 0
            for i, ub in enumerate(_HIST_BUCKETS):
                cumulative += buckets[i]
                lines.append(f'{m}_bucket{{le="{ub}"}} {cumulative}')
            cumulative += buckets[-1]
            lines.append(f'{m}_bucket{{le="+Inf"}} {cumulative}')
            lines.append(f"{m}_sum {_hist_sum[name]}")
            lines.append(f"{m}_count {_hist_n[name]}")
        lines.append("# TYPE engram_uptime_seconds gauge")
        lines.append(f"engram_uptime_seconds {time.time() - _started_at}")
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Test helper."""
    with _lock:
        _counters.clear()
        _hist_counts.clear()
        _hist_sum.clear()
        _hist_n.clear()
