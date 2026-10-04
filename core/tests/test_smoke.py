import pytest
from django.conf import settings
from django.db import connection


def test_settings_use_postgres():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


@pytest.mark.django_db
def test_database_connection_works():
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


@pytest.mark.django_db
def test_postgres_supports_required_features():
    """The schema needs JSONB and gin/btree index support. Fail loudly here
    rather than deep inside a migration."""
    with connection.cursor() as cur:
        cur.execute("SELECT ('{\"a\": 1}'::jsonb ->> 'a')::int")
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT count(*) FROM pg_am WHERE amname IN ('gin', 'btree')")
        assert cur.fetchone()[0] == 2


def test_api_versioning_is_configured():
    assert settings.REST_FRAMEWORK["DEFAULT_VERSION"] == "v1"
    assert settings.REST_FRAMEWORK["ALLOWED_VERSIONS"] == ["v1"]
