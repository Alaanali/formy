import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from analytics.reporting import results
from responses.services import save_answers, start_submission

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def complete(version, answers):
    submission = start_submission(version)
    save_answers(submission, answers, complete=True)


def test_a_repeat_read_is_served_from_cache(live_survey, ids):
    """Two aggregates to read the data clock, and nothing else: the payload
    itself comes from the cache."""
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    results(live_survey)  # warm

    with CaptureQueriesContext(connection) as ctx:
        results(live_survey)

    assert len(ctx.captured_queries) == 2


def test_a_new_response_is_visible_immediately(live_survey, ids):
    """The point of keying on freshness. A TTL made the dashboard lag by its
    full duration -- 60 seconds, measured -- which is not real-time."""
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    before = results(live_survey)["funnel"]["completed"]

    complete(live_survey, {ids["country"]: "eg", ids["age"]: 40})

    assert results(live_survey)["funnel"]["completed"] == before + 1


def test_the_expiry_cannot_serve_stale_data(live_survey, ids):
    """Correctness comes from the key, so an entry at an old key is simply
    never read again -- the TTL only bounds memory."""
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    stale = results(live_survey)

    complete(live_survey, {ids["country"]: "eg", ids["age"]: 31})

    assert results(live_survey) != stale


def test_the_payload_is_the_same_whether_cached_or_not(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    cold = results(live_survey)
    warm = results(live_survey)

    assert cold == warm


def test_clearing_the_cache_recomputes(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    results(live_survey)
    cache.clear()

    with CaptureQueriesContext(connection) as ctx:
        results(live_survey)

    assert len(ctx.captured_queries) > 0
