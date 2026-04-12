"""Pytest configuration for all tests."""

import os

# Run Celery tasks synchronously (no broker needed for tests)
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
# Security tokens for auth tests
os.environ["ACCESS_SECRET_KEY"] = "test-secret-key-for-testing-only-32-chars"
os.environ["SECRET_KEY"] = "test-deployer-secret-for-testing-only"
os.environ["EMAILS_ENABLED"] = "false"
