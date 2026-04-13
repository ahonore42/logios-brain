"""Celery application configuration."""

import os

from celery import Celery

from app import config
from app import telemetry

# Initialize OTel Celery instrumentation.
telemetry.configure()

celery_app = Celery(
    "logios",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Run tasks synchronously when CELERY_TASK_ALWAYS_EAGER is set.
    # Useful for testing without a broker.
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true",
)
