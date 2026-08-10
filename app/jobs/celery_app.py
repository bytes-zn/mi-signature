"""Celery application instance.

Worker:   ``celery -A app.jobs.celery_app worker``
Beat:     ``celery -A app.jobs.celery_app beat``
"""

from celery import Celery

from app.config.settings import get_settings


def create_celery() -> Celery:
    """Build the Celery app from application settings."""
    settings = get_settings()
    app = Celery(
        "bytes_signature_service",
        broker=settings.resolved_celery_broker_url,
        backend=settings.resolved_celery_result_backend,
        include=["app.jobs.tasks"],
    )
    app.conf.update(
        task_track_started=True,
        timezone="UTC",
    )
    if settings.graph_sync_interval_minutes > 0:
        app.conf.beat_schedule = {
            "graph-sync-all-tenants": {
                "task": "app.jobs.tasks.sync_all_tenants",
                "schedule": settings.graph_sync_interval_minutes * 60,
            }
        }
    return app


celery_app = create_celery()
