import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import Membership
from exports.models import Export
from invitations.services import create_batch
from responses.services import save_answers, start_submission
from surveys.models import Section, Survey, SurveyAccess
from surveys.publish import publish

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole
pytestmark = pytest.mark.django_db


def count(client, url: str) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == 200, f"{url} -> {response.status_code}"
    return len(captured)


def warm_count(client, url: str) -> int:
    """Queries for one request, with every cache already populated.

    Both samples have to be warm. The schema cache costs an extra read when
    cold, and the results cache is keyed on data freshness -- so growing the
    collection invalidates it, and comparing a warm sample against a cold one
    measures the cache rather than the query shape.
    """
    count(client, url)
    return count(client, url)


def assert_constant(client, url: str, add) -> None:
    """Grow the collection twice and require the query count to hold."""
    add(3)
    first = warm_count(client, url)
    add(3)
    second = warm_count(client, url)
    assert second == first, (
        f"{url} grew from {first} to {second} queries when the collection doubled"
    )


@pytest.fixture
def owner_client(org, member_factory):
    owner = member_factory(org, OrgRole.OWNER)
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


def test_organization_surveys(owner_client, org):
    def add(n):
        for _ in range(n):
            Survey.objects.create(organization=org, name=uuid.uuid4().hex, slug=uuid.uuid4().hex)

    assert_constant(owner_client, f"/api/v1/organizations/{org.id}/surveys/", add)


def test_organization_members(owner_client, org, member_factory):
    assert_constant(
        owner_client,
        f"/api/v1/organizations/{org.id}/members/",
        lambda n: [member_factory(org, OrgRole.MEMBER) for _ in range(n)],
    )


def test_survey_access_grants(owner_client, survey, member_factory, grant):
    assert_constant(
        owner_client,
        f"/api/v1/surveys/{survey.id}/access/",
        lambda n: [
            grant(member_factory(survey.organization, OrgRole.MEMBER), survey, SurveyRole.VIEWER)
            for _ in range(n)
        ],
    )


def test_survey_versions(owner_client, survey):
    from surveys.models import SurveyVersion

    def add(n):
        for _ in range(n):
            SurveyVersion.objects.filter(survey=survey, status="draft").delete()
            SurveyVersion.objects.create_draft(survey)

    assert_constant(owner_client, f"/api/v1/surveys/{survey.id}/versions/", add)


def test_version_sections(owner_client, draft):
    def add(n):
        for _ in range(n):
            Section.objects.create(
                version=draft, key=uuid.uuid4().hex[:8], title="S", order=0, content={}
            )

    assert_constant(owner_client, f"/api/v1/versions/{draft.id}/sections/", add)


def _complete(version, ids):
    submission = start_submission(version)
    save_answers(
        submission,
        {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1"},
        complete=True,
    )
    return submission


def test_version_submissions(owner_client, live_survey, ids):
    assert_constant(
        owner_client,
        f"/api/v1/versions/{live_survey.id}/submissions/",
        lambda n: [_complete(live_survey, ids) for _ in range(n)],
    )


def test_version_results(owner_client, live_survey, ids):
    """The headline scalability claim: reading aggregates must not scale with
    the responses already collected."""
    assert_constant(
        owner_client,
        f"/api/v1/versions/{live_survey.id}/results/",
        lambda n: [_complete(live_survey, ids) for _ in range(n)],
    )


def test_one_submission_answers(owner_client, live_survey, ids):
    """Grows the survey's responses, not this submission's answers: a
    response detail must not pay for its siblings."""
    submission = _complete(live_survey, ids)
    assert_constant(
        owner_client,
        f"/api/v1/submissions/{submission.id}/answers/",
        lambda n: [_complete(live_survey, ids) for _ in range(n)],
    )


def test_version_exports(owner_client, live_survey):
    assert_constant(
        owner_client,
        f"/api/v1/versions/{live_survey.id}/exports/",
        lambda n: [
            Export.objects.create(survey_version=live_survey, status=Export.Status.PENDING)
            for _ in range(n)
        ],
    )


def test_version_invitations(owner_client, live_survey):
    assert_constant(
        owner_client,
        f"/api/v1/versions/{live_survey.id}/invitations/",
        lambda n: [
            create_batch(live_survey, [f"{uuid.uuid4().hex}@example.com"]) for _ in range(n)
        ],
    )


def test_respondent_submission_state(live_survey, ids):
    """The respondent's own view, which is the highest-volume read."""
    from responses.permissions import RESUME_TOKEN_HEADER

    api = APIClient()
    started = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").json()
    api.credentials(
        **{f"HTTP_{RESUME_TOKEN_HEADER.upper().replace('-', '_')}": started["resume_token"]}
    )
    url = f"/api/v1/public/submissions/{started['id']}/"

    assert_constant(api, url, lambda n: [_complete(live_survey, ids) for _ in range(n)])


def test_publishing_does_not_scale_with_sections(draft):
    """Publish reads every section once, not once per field."""

    def sections(n):
        for _ in range(n):
            Section.objects.create(
                version=draft,
                key=uuid.uuid4().hex[:8],
                title="S",
                order=0,
                content={str(uuid.uuid7()): {"type": "text", "label": "Q"}},
            )

    sections(3)
    with CaptureQueriesContext(connection) as first:
        publish(draft)

    from surveys.models import SurveyVersion

    second_draft = SurveyVersion.objects.create_draft(draft.survey)
    for _ in range(6):
        Section.objects.create(
            version=second_draft,
            key=uuid.uuid4().hex[:8],
            title="S",
            order=0,
            content={str(uuid.uuid7()): {"type": "text", "label": "Q"}},
        )
    with CaptureQueriesContext(connection) as second:
        publish(second_draft)

    assert len(second) == len(first), (
        f"publish grew from {len(first)} to {len(second)} queries with twice the sections"
    )
