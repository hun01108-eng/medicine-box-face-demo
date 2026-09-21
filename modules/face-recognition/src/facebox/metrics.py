import math
from statistics import median


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def summarize_latencies(latencies: list[float]) -> dict[str, float | int | bool]:
    if not latencies:
        raise ValueError("at least one latency measurement is required")
    p50 = float(median(latencies))
    p95 = float(_nearest_rank(latencies, 0.95))
    return {
        "trials": len(latencies),
        "p50_seconds": round(p50, 4),
        "p95_seconds": round(p95, 4),
        "max_seconds": round(max(latencies), 4),
        "p95_within_3s": p95 <= 3.0,
    }
