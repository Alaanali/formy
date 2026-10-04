from .base import *  # noqa: F403
from .base import env

DEBUG = False

# Required rather than defaulted, so a missing one is a refusal at startup
# instead of something discovered later: an unset ALLOWED_HOSTS inherits the
# localhost default and turns every real request into a puzzling 400.
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", required=True).split(",") if h]

# Django checks the Origin header on session-authenticated writes, and behind
# a TLS-terminating proxy it cannot infer the public scheme and host.
CSRF_TRUSTED_ORIGINS = [
    origin for origin in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# PgBouncer in transaction mode cannot hold server-side cursors.
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # noqa: F405

# Production only: in development django.contrib.staticfiles serves these,
# and running WhiteNoise there just warns about a directory collectstatic
# has not written yet.
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed filenames plus a manifest, so static assets can be cached hard.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Unhandled errors have to reach the platform's log, or a failure in
# production is invisible.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
