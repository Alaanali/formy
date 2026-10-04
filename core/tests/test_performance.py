import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import Membership
from responses.permissions import RESUME_TOKEN_HEADER
from responses.services import save_answers, start_submission
from surveys.models import Survey, SurveyAccess

OrgRole = Membership.OrgRole
pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


def token_client(api, started):
    api.credentials(
        **{f"HTTP_{RESUME_TOKEN_HEADER.upper().replace('-', '_')}": started["resume_token"]}
    )
    return api


def test_reading_submission_state_does_not_scale_with_answers(api, live_survey, ids):
    """The schema comes from cache and answers are one query, so a form with
    five answers costs the same as one with two."""
    started = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").json()
    client = token_client(api, started)
    url = f"/api/v1/public/submissions/{started['id']}/"

    client.patch(url, {"answers": {ids["country"]: "sa"}}, format="json")
    client.get(url)  # warm the schema cache

    with CaptureQueriesContext(connection) as few:
        client.get(url)

    client.patch(
        url,
        {"answers": {ids["age"]: 30, ids["comments"]: "x", ids["city"]: "riyadh"}},
        format="json",
    )

    with CaptureQueriesContext(connection) as many:
        client.get(url)

    assert len(many.captured_queries) == len(few.captured_queries)


def test_autosave_writes_a_batch_in_one_statement(api, live_survey, ids):
    """bulk_create with update_conflicts: a sixty-field submission should be
    one INSERT, not sixty round trips."""
    started = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").json()
    client = token_client(api, started)
    url = f"/api/v1/public/submissions/{started['id']}/"
    client.get(url)  # warm caches

    with CaptureQueriesContext(connection) as ctx:
        client.patch(
            url,
            {"answers": {ids["country"]: "sa", ids["age"]: 30, ids["national_id"]: "123456"}},
            format="json",
        )

    inserts = [q for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith("INSERT")]
    assert len(inserts) == 1


def test_listing_surveys_has_no_n_plus_one(api, org, member_factory):
    """published_version reads each survey's versions; without prefetching
    this grows one query per row."""
    from django.contrib.auth import get_user_model

    admin = member_factory(org, OrgRole.ADMIN)

    def measure():
        # A fresh user instance each time: effective_role memoises on the
        # instance, so reusing one would make the second measurement cheaper
        # for a reason unrelated to row count.
        api.force_authenticate(user=get_user_model().objects.get(pk=admin.pk))
        with CaptureQueriesContext(connection) as ctx:
            api.get(f"/api/v1/organizations/{org.id}/surveys/")
        return len(ctx.captured_queries)

    for n in range(3):
        Survey.objects.create(organization=org, name=f"S{n}", slug=f"s{n}")
    few = measure()

    for n in range(3, 12):
        Survey.objects.create(organization=org, name=f"S{n}", slug=f"s{n}")
    many = measure()

    assert many == few


def test_permission_checks_are_resolved_once_per_request(api, live_survey, member_factory, grant):
    """effective_role is memoised per user instance, so serialising a page of
    rows resolves each survey once rather than once per row."""
    analyst = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(analyst, live_survey.survey, SurveyAccess.SurveyRole.ANALYST)
    api.force_authenticate(user=analyst)

    for _ in range(5):
        submission = start_submission(live_survey)
        save_answers(submission, {}, complete=False)

    with CaptureQueriesContext(connection) as ctx:
        api.get(f"/api/v1/versions/{live_survey.id}/submissions/")

    membership_queries = [q for q in ctx.captured_queries if "accounts_membership" in q["sql"]]
    assert len(membership_queries) <= 2
