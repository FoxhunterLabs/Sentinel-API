from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latency",
    ["method", "path"],
)

PREDICTIONS_PER_SECOND = Gauge(
    "predictions_per_second",
    "Predictions/sec (per pod)",
)

PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Total predictions",
)
