from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = "test-only-key"

DATABASES["default"]["NAME"] = env("POSTGRES_DB", "formy")  # noqa: F405

# Fast, deterministic hashing -- tests create a lot of users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tests must not depend on a live Redis.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Tasks run inline, so the suite needs no broker and no worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
