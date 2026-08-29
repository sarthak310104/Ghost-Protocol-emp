from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ghost_protocol",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.tasks.ingest_spans_batch": {"queue": "ingestion"},
        "app.workers.tasks.ingest_metrics_batch": {"queue": "ingestion"},
        "app.workers.tasks.update_graph_and_baselines": {"queue": "graph"},
        "app.workers.tasks.scan_for_anomalies": {"queue": "incident"},
        "app.workers.tasks.run_bottleneck_scan": {"queue": "graph"},
        "app.workers.tasks.refresh_all_reference_baselines": {"queue": "graph"},
        "app.workers.tasks.diagnose_incident": {"queue": "reasoning"},
    },
    beat_schedule={
        "scan-for-anomalies-every-30s": {
            "task": "app.workers.tasks.scan_for_anomalies",
            "schedule": 30.0,
        },
        "bottleneck-scan-every-5m": {
            "task": "app.workers.tasks.run_bottleneck_scan",
            "schedule": 300.0,
        },
        "refresh-reference-baselines-hourly": {
            # Promotes each edge's fast "current" EWMA into the slow
            # "reference" baseline anomaly detection compares against.
            # Without this scheduled, edges never get a reference and
            # scan_for_anomalies has nothing to compare "current" to --
            # this was previously only callable manually, which meant
            # anomaly detection silently never fired in a fresh deployment.
            "task": "app.workers.tasks.refresh_all_reference_baselines",
            "schedule": 3600.0,
        },
    },
)
