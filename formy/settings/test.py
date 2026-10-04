from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = "test-only-key"

DATABASES["default"]["NAME"] = env("POSTGRES_DB", "formy")  # noqa: F405

# Fast, deterministic hashing -- tests create a lot of users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tests must not depend on a live Redis.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

FIELD_ENCRYPTION_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

# Tasks run inline, so the suite needs no broker and no worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Keep uploaded and generated files out of the project tree.
import tempfile  # noqa: E402

MEDIA_ROOT = tempfile.mkdtemp(prefix="formy-test-media-")

# Off by default: a shared rate limit would make unrelated tests fail
# depending on execution order. Throttling is tested with override_settings.
# None means unthrottled; an absent scope would raise KeyError.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        "auth": None,
        "submission_start": None,
        "submission_write": None,
        "submission_upload": None,
    },
}

# Mail is captured in memory, never sent.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
