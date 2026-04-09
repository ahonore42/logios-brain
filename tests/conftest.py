"""Pytest configuration for all tests."""
import os

# Run Celery tasks synchronously (no broker needed for tests)
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
