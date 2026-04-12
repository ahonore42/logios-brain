"""Background task workers — Celery configuration and task definitions."""

from app.automation.celery import celery_app
from app.automation.tasks import (
    task_extract_entities,
    task_upsert_neo4j,
    task_upsert_qdrant,
)

__all__ = ["celery_app", "task_extract_entities", "task_upsert_neo4j", "task_upsert_qdrant"]
