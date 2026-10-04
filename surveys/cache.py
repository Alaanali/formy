from __future__ import annotations

from django.core.cache import cache

from surveys.document import Document, parse
from surveys.models import SurveyVersion

#: No expiry: the key derives from an immutable version, so an entry can only
#: ever be correct. Eviction costs one row read.
SCHEMA_TIMEOUT = None


def schema_cache_key(version_id) -> str:
    return f"survey_version:{version_id}:schema"


def get_schema(version: SurveyVersion) -> dict:
    """The assembled document, from cache when the version is published."""
    if version.status != SurveyVersion.Status.PUBLISHED:
        return version.schema or {}

    key = schema_cache_key(version.id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    schema = version.schema or {}
    cache.set(key, schema, SCHEMA_TIMEOUT)
    return schema


def get_schema_by_id(version_id) -> dict | None:
    """Read a published schema without loading the row when it is cached."""
    cached = cache.get(schema_cache_key(version_id))
    if cached is not None:
        return cached

    version = (
        SurveyVersion.objects.filter(pk=version_id, status=SurveyVersion.Status.PUBLISHED)
        .only("id", "status", "schema")
        .first()
    )
    if version is None:
        return None
    return get_schema(version)


def warm(version: SurveyVersion) -> None:
    """Populate the cache at publish, so a launch burst does not stampede."""
    if version.status == SurveyVersion.Status.PUBLISHED:
        cache.set(schema_cache_key(version.id), version.schema or {}, SCHEMA_TIMEOUT)


def get_document(version: SurveyVersion) -> Document:
    """The parsed document for a version."""
    return parse(get_schema(version))
