import pytest
from rest_framework.test import APIClient

from accounts.models import Membership
from responses.services import save_answers, start_submission
from surveys.models import SurveyAccess

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole
pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def as_user(api):
    def login(user):
        api.force_authenticate(user=user)
        return api

    return login


@pytest.fixture
def analyst(live_survey, member_factory, grant):
    user = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(user, live_survey.survey, SurveyRole.ANALYST)
    return user


@pytest.fixture
def viewer(live_survey, member_factory, grant):
    user = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(user, live_survey.survey, SurveyRole.VIEWER)
    return user


def complete(version, answers):
    submission = start_submission(version)
    save_answers(submission, answers, complete=True)
    return submission


def field_of(body, field_id):
    return next(f for f in body["fields"] if f["field_id"] == field_id)


# --- results -----------------------------------------------------------------


def test_results_report_the_funnel(as_user, live_survey, analyst, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    start_submission(live_survey)  # abandoned

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()

    assert body["funnel"]["started"] == 2
    assert body["funnel"]["completed"] == 1
    assert body["funnel"]["completion_rate"] == 0.5


def test_percentages_use_eligible_respondents_not_total_submissions(
    as_user, live_survey, analyst, ids
):
    """The city question sits in a section only Saudi respondents see.
    Against all submissions it would read 33%; against the people actually
    asked it is 100%, which is the only honest number."""
    complete(live_survey, {ids["country"]: "sa", ids["age"]: 30, ids["city"]: "riyadh"})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()
    city = field_of(body, ids["city"])

    assert city["eligible"] == 1
    assert city["answered"] == 1


def test_choice_distribution_is_reported(as_user, live_survey, analyst, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "sa", ids["age"]: 18})

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()
    counts = {b["bucket"]: b["count"] for b in field_of(body, ids["country"])["buckets"]}

    assert counts == {"eg": 2, "sa": 1}


def test_numeric_summary_is_reported(as_user, live_survey, analyst, ids):
    for age in (20, 40, 60):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: age})

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()
    numeric = field_of(body, ids["age"])["numeric"]

    assert numeric == {"sum": 120.0, "min": 20.0, "max": 60.0, "average": 40.0}


def test_an_unanswered_eligible_field_is_visible_in_the_counts(as_user, live_survey, analyst, ids):
    """eligible minus answered is the skip count; the payload reports the two
    numbers and leaves the subtraction to the client."""
    complete(live_survey, {ids["country"]: "eg"})

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()
    age = field_of(body, ids["age"])

    assert (age["eligible"], age["answered"]) == (1, 0)


def test_encrypted_fields_say_why_they_have_no_distribution(as_user, live_survey, analyst, ids):
    """Stated, not silently omitted: a consumer should be able to tell a
    deliberate limitation from missing data."""
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1234567890"})

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/results/").json()
    nid = field_of(body, ids["national_id"])

    assert nid["distribution_available"] is False
    assert "encrypted" in nid["reason"]
    assert nid["answered"] == 1  # counting it is still fine
    assert "buckets" not in nid


def test_survey_results_use_the_latest_published_version(as_user, live_survey, analyst, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    response = as_user(analyst).get(f"/api/v1/surveys/{live_survey.survey_id}/results/")

    assert response.status_code == 200
    assert response.json()["version_number"] == live_survey.version_number


def test_results_do_not_scale_with_response_count(as_user, live_survey, analyst, ids):
    """Every number comes from the rollups, so the query count depends on the
    survey's shape and not on how many people answered it."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for _ in range(5):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    from django.core.cache import cache

    client = as_user(analyst)
    client.get(f"/api/v1/versions/{live_survey.id}/results/")  # warm the schema

    # The results cache is cleared before each measurement: this test is
    # about the query SHAPE, and a cache hit would hide a scan that grew.
    cache.delete_pattern = None  # not all backends have it; clear() is enough
    cache.clear()
    with CaptureQueriesContext(connection) as few:
        client.get(f"/api/v1/versions/{live_survey.id}/results/")

    for _ in range(15):
        complete(
            live_survey,
            {ids["country"]: "sa", ids["age"]: 40, ids["city"]: "riyadh"},
        )

    cache.clear()
    with CaptureQueriesContext(connection) as many:
        client.get(f"/api/v1/versions/{live_survey.id}/results/")

    assert len(many.captured_queries) == len(few.captured_queries)


# --- capability separation ---------------------------------------------------


def test_a_viewer_sees_aggregates(as_user, live_survey, viewer, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    assert as_user(viewer).get(f"/api/v1/versions/{live_survey.id}/results/").status_code == 200


def test_a_viewer_cannot_list_individual_responses(as_user, live_survey, viewer, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    response = as_user(viewer).get(f"/api/v1/versions/{live_survey.id}/submissions/")

    assert response.status_code == 403


def test_an_analyst_can_list_individual_responses(as_user, live_survey, analyst, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    response = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/submissions/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert "resume_token" not in response.json()[0]


def test_an_analyst_reads_decrypted_answers(as_user, live_survey, analyst, ids):
    submission = complete(
        live_survey, {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1234567890"}
    )

    body = as_user(analyst).get(f"/api/v1/submissions/{submission.id}/answers/").json()

    assert body["answers"][ids["national_id"]] == "1234567890"


def test_a_viewer_cannot_read_an_individual_response(as_user, live_survey, viewer, ids):
    submission = complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    response = as_user(viewer).get(f"/api/v1/submissions/{submission.id}/answers/")

    assert response.status_code == 403


def test_results_of_an_invisible_survey_are_404(as_user, live_survey, member_factory, ids):
    outsider = member_factory(live_survey.survey.organization, OrgRole.MEMBER)

    response = as_user(outsider).get(f"/api/v1/versions/{live_survey.id}/results/")

    assert response.status_code == 404


def test_reading_an_individual_response_writes_an_audit_entry(as_user, live_survey, analyst, ids):
    from auditlog.models import LogEntry

    submission = complete(
        live_survey, {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1234567890"}
    )
    as_user(analyst).get(f"/api/v1/submissions/{submission.id}/answers/")

    entries = LogEntry.objects.filter(action=LogEntry.Action.ACCESS)
    assert entries.count() == 1
    assert entries.first().additional_data["event"] == "pii.access"
