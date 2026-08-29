"""
edge_metrics.py — CPU and RAM metrics sampler with 1-second caching.

Provides ``get_edge_compute_metrics()`` which returns a dict of
``{"cpu_percent": float, "ram_percent": float}`` throttled to one
psutil sample per second to avoid performance overhead.
"""

import time


_last_cpu_sample_ts = 0.0
_cached_cpu_pct = 0.0
_cached_ram_pct = 0.0


def get_edge_compute_metrics() -> dict:
    """Sample CPU % and RAM % using psutil with 1-second cached throttling."""
    global _last_cpu_sample_ts, _cached_cpu_pct, _cached_ram_pct
    now = time.time()
    if (now - _last_cpu_sample_ts) >= 1.0:
        try:
            import psutil
            _cached_cpu_pct = round(psutil.cpu_percent(interval=None), 1)
            _cached_ram_pct = round(psutil.virtual_memory().percent, 1)
            _last_cpu_sample_ts = now
        except Exception:
            pass
    return {
        "cpu_percent": _cached_cpu_pct,
        "ram_percent": _cached_ram_pct,
    }
