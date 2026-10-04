import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value or ""


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-override-in-production")
DEBUG = env("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    # project
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "formy.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "formy.wsgi.application"
ASGI_APPLICATION = "formy.asgi.application"

# Postgres only. The schema depends on JSONB, GIN indexes, partial unique
# constraints and check constraints -- none of which SQLite supports.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "formy"),
        "USER": env("POSTGRES_USER", "formy"),
        "PASSWORD": env("POSTGRES_PASSWORD", "formy"),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5440"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6390/0")

# A separate database from the broker, deliberately. Django's RedisCache
# clear() issues FLUSHDB, which on a shared database would delete every
# queued and unacknowledged Celery message along with the cached schemas.
CACHE_URL = env("CACHE_URL", "redis://127.0.0.1:6390/1")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_URL,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# collectstatic needs somewhere to write, and the admin is unusable without
# it -- no CSS, which looks like a broken deployment rather than a missing
# step.
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- celery -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"

# Acknowledge after the task returns, so a worker killed mid-task leaves the
# message to be redelivered rather than silently dropping it.
CELERY_TASK_ACKS_LATE = True
# One task at a time per worker process: these tasks are long and uneven, so
# prefetching several would leave them queued behind a slow one.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Token first: a non-browser client has no way to obtain a session,
        # and Django's admin login form rejects any user who is not staff.
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "core.api.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Formy",
    "DESCRIPTION": (
        "Enterprise survey platform: a dynamic builder with cross-section "
        "conditional logic, anonymous resumable submission, field-level "
        "encryption, per-survey RBAC and incrementally maintained analytics.\n\n"
        "**Versioning.** The version is in the URL path (`/api/v1/`), so a "
        "deployed client is pinned to a contract and a future v2 can run "
        "alongside v1 rather than replacing it."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
}
