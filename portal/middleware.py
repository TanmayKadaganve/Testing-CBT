import threading
import time
import os
from collections import deque
from django.utils import timezone

# Thread-safe ring buffer storing up to 1000 recent request measurements
_METRICS_LOCK = threading.Lock()
_REQUEST_BUFFER = deque(maxlen=1000)
_SERVER_START_TIME = timezone.now()


class PerformanceMonitoringMiddleware:
    """
    Lightweight, thread-safe in-memory middleware that records server-side request latency.
    Zero database writes. Zero storage of passwords, tokens, query params, or student code.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.perf_counter()
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Sanitize path: never store query string or body
        path = request.path[:100]

        # Ignore static files from cluttering performance samples if needed,
        # but keep application and dashboard requests
        if not path.startswith("/static/"):
            with _METRICS_LOCK:
                _REQUEST_BUFFER.append({
                    "timestamp": timezone.now(),
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                })

        return response


def get_performance_metrics():
    """
    Computes real server latency statistics from the in-memory ring buffer.
    Never fabricates metrics; returns None / 'Insufficient data' if samples are too few.
    """
    with _METRICS_LOCK:
        samples = list(_REQUEST_BUFFER)

    sample_count = len(samples)
    if sample_count == 0:
        return {
            "sample_count": 0,
            "avg_latency_ms": None,
            "median_latency_ms": None,
            "p95_latency_ms": None,
            "slow_requests_count": 0,
            "count_2xx": 0,
            "count_4xx": 0,
            "count_5xx": 0,
            "server_start_time": _SERVER_START_TIME,
            "recent_requests": [],
            "worker_pid": os.getpid(),
            "scope": "current web worker process only",
        }

    durations = sorted([s["duration_ms"] for s in samples])
    total_duration = sum(durations)
    avg_latency = round(total_duration / sample_count, 2)

    # Median and P95 calculation
    median_latency = None
    p95_latency = None
    if sample_count >= 5:
        mid = sample_count // 2
        median_latency = durations[mid] if sample_count % 2 != 0 else round((durations[mid - 1] + durations[mid]) / 2, 2)

        p95_index = int(sample_count * 0.95)
        p95_latency = durations[min(p95_index, sample_count - 1)]

    slow_count = sum(1 for d in durations if d >= 500)
    count_2xx = sum(1 for s in samples if 200 <= s["status_code"] < 300)
    count_4xx = sum(1 for s in samples if 400 <= s["status_code"] < 500)
    count_5xx = sum(1 for s in samples if 500 <= s["status_code"] < 600)

    # Latest 30 requests
    recent = list(reversed(samples[-30:]))

    return {
        "sample_count": sample_count,
        "avg_latency_ms": avg_latency,
        "median_latency_ms": median_latency,
        "p95_latency_ms": p95_latency,
        "slow_requests_count": slow_count,
        "count_2xx": count_2xx,
        "count_4xx": count_4xx,
        "count_5xx": count_5xx,
        "server_start_time": _SERVER_START_TIME,
        "recent_requests": recent,
        "worker_pid": os.getpid(),
        "scope": "current web worker process only",
    }
