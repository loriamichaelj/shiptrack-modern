"""Prometheus metrics (REM-15). They are served on port 9090 only, never on 8000: the ALB forwards
everything on 8000, so /metrics there would be public."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["route", "method", "status_class"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
EVENTS_ENQUEUED = Counter("shiptrack_events_enqueued_total", "Events sent to the queue", ["result"])
EVENTS_PROCESSED = Counter(
    "shiptrack_events_processed_total", "Events handled by the worker", ["result"]
)
EVENT_APPLY_LAG = Histogram(
    "shiptrack_event_apply_lag_seconds",
    "Seconds from the API receiving an event to the worker applying it",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
NOTIFICATIONS_SENT = Counter(
    "shiptrack_notifications_sent_total", "Notifications sent", ["detail_type"]
)
SLA_BREACHES = Counter("shiptrack_sla_breaches_total", "Shipments flagged as SLA breaches")
POD_UPLOADS = Counter("shiptrack_pod_uploads_total", "Proof-of-delivery uploads", ["result"])
POD_NOT_MIGRATED = Counter(
    "shiptrack_pod_not_migrated_total", "Downloads of a POD that is still on a legacy disk"
)
DB_POOL_CHECKED_OUT = Gauge("shiptrack_db_pool_checked_out", "Database connections in use")
