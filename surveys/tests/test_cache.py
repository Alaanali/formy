import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from surveys.cache import get_schema, get_schema_by_id, schema_cache_key
from surveys.models import Section
from surveys.publish import publish
from surveys.tests.factories import choice, fid

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def published(draft, django_capture_on_commit_callbacks):
    """Warming is deferred to transaction commit, so a publish that rolls
    back leaves no cache entry. Tests run inside a transaction, so the
    callbacks are captured and executed explicitly."""
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={fid(): choice()})
    with django_capture_on_commit_callbacks(execute=True):
        version = publish(draft)
    return version


def test_publishing_warms_the_cache(published):
    """The first respondent after a release should not pay for the miss, and
    a launch burst should not stampede the database."""
    assert cache.get(schema_cache_key(published.id)) is not None


def test_a_published_schema_is_served_from_cache(published):
    get_schema(published)

    with CaptureQueriesContext(connection) as ctx:
        schema = get_schema_by_id(published.id)

    assert schema["eval_order"]
    assert len(ctx.captured_queries) == 0


def test_a_cold_cache_costs_one_query(published):
    cache.clear()

    with CaptureQueriesContext(connection) as ctx:
        get_schema_by_id(published.id)

    assert len(ctx.captured_queries) == 1


def test_drafts_are_never_cached(draft):
    """A draft changes on every builder keystroke; caching it would create
    the invalidation problem this design avoids."""
    get_schema(draft)

    assert cache.get(schema_cache_key(draft.id)) is None


def test_a_new_version_gets_its_own_key(published, survey, django_capture_on_commit_callbacks):
    """Immutability is what removes invalidation: a change produces a new
    key rather than a stale entry at the old one."""
    from surveys.publish import derive_draft

    v2 = derive_draft(published)
    with django_capture_on_commit_callbacks(execute=True):
        published_v2 = publish(v2)

    assert schema_cache_key(published.id) != schema_cache_key(published_v2.id)
    assert cache.get(schema_cache_key(published.id)) is not None


def test_unknown_version_returns_none(published):
    import uuid

    assert get_schema_by_id(uuid.uuid7()) is None


def test_unpublished_versions_are_not_served_by_id(draft):
    assert get_schema_by_id(draft.id) is None


def test_a_rolled_back_publish_leaves_no_cache_entry(draft):
    """Warming on commit rather than inline: a failed transaction must not
    leave a schema cached for a version that was never published."""
    from django.db import transaction

    Section.objects.create(version=draft, key="s1", title="One", order=1, content={fid(): choice()})

    with pytest.raises(RuntimeError), transaction.atomic():
        publish(draft)
        raise RuntimeError("something later in the request failed")

    assert cache.get(schema_cache_key(draft.id)) is None
