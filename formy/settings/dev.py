from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key")
