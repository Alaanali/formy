import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import Membership
from exports.models import Export
from responses.models import Answer, Submission
from responses.permissions import RESUME_TOKEN_HEADER
from responses.services import save_answers, start_submission
from surveys.models import Survey, SurveyAccess, SurveyVersion

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole
pytestmark = pytest.mark.django_db

SQL_PAYLOADS = [
    "'; DROP TABLE responses_answer; --",
    "1' OR '1'='1",
    "admin'--",
    "'; UPDATE surveys_survey SET name='owned'; --",
    "\\'; DELETE FROM accounts_organization WHERE '1'='1",
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    "<svg/onload=alert(1)>",
]


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
def respondent(api, live_survey):
    started = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").json()
    api.credentials(
        **{f"HTTP_{RESUME_TOKEN_HEADER.upper().replace('-', '_')}": started["resume_token"]}
    )
    return api, started


# --- SQL injection -----------------------------------------------------------


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_injection_in_an_answer_value_is_stored_as_data(respondent, live_survey, ids, payload):
    """The ORM parameterises, so a payload is a string and nothing else. The
    assertion that matters is that the tables are still there afterwards."""
    client, started = respondent

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["comments"]: payload[:50], ids["country"]: "sa"}},
        format="json",
    )

    assert response.status_code == 200
    assert Survey.objects.exists()
    assert SurveyVersion.objects.exists()
    assert Answer.objects.filter(value=payload[:50]).exists()


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_injection_through_a_field_id_cannot_reach_sql(respondent, payload):
    """field_id is a UUIDField, so a non-UUID is rejected before any query is
    built from it."""
    client, started = respondent

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {payload: "x"}},
        format="json",
    )

    assert response.status_code == 400
    assert Answer.objects.count() == 0


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_injection_in_a_url_identifier_is_a_404_not_an_error(as_user, org, member_factory, payload):
    admin = member_factory(org, OrgRole.ADMIN)

    response = as_user(admin).get(f"/api/v1/surveys/{payload}/")

    assert response.status_code == 404


def test_injection_in_a_survey_name_is_stored_verbatim(as_user, org, member_factory):
    admin = member_factory(org, OrgRole.ADMIN)
    payload = "'; DROP TABLE surveys_survey; --"

    response = as_user(admin).post(
        f"/api/v1/organizations/{org.id}/surveys/",
        {"name": payload, "slug": "injection"},
        format="json",
    )

    assert response.status_code == 201
    assert Survey.objects.filter(name=payload).exists()


# --- XSS ---------------------------------------------------------------------


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_script_payloads_round_trip_as_json_strings(respondent, ids, payload):
    """The API only ever emits JSON, so a payload comes back as inert text.
    What must not happen is the server rendering it, or a content type that
    a browser would treat as markup."""
    client, started = respondent
    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["country"]: "sa", ids["comments"]: payload}},
        format="json",
    )

    response = client.get(f"/api/v1/public/submissions/{started['id']}/")

    assert response["Content-Type"].startswith("application/json")
    assert response.json()["answers"][ids["comments"]] == payload


def test_html_in_a_survey_name_is_served_as_inert_json(as_user, org, member_factory):
    """JSON does not require escaping `<`, and DRF does not escape it. What
    makes the payload inert is the content type plus nosniff: a browser is
    told this is JSON and forbidden from guessing otherwise. Asserting the
    absence of the characters would be testing something untrue."""
    admin = member_factory(org, OrgRole.ADMIN)
    response = as_user(admin).post(
        f"/api/v1/organizations/{org.id}/surveys/",
        {"name": "<script>alert(1)</script>", "slug": "xss"},
        format="json",
    )

    assert response["Content-Type"].startswith("application/json")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response.json()["name"] == "<script>alert(1)</script>"


# --- authorization bypass ----------------------------------------------------


def test_cannot_read_another_tenants_survey_by_guessing_its_id(
    as_user, org, other_org, member_factory
):
    theirs = Survey.objects.create(organization=other_org, name="Theirs", slug="t")
    admin = member_factory(org, OrgRole.ADMIN)

    assert as_user(admin).get(f"/api/v1/surveys/{theirs.id}/").status_code == 404


def test_a_missing_survey_and_a_forbidden_one_are_indistinguishable(
    as_user, org, other_org, member_factory
):
    """Both 404. A 403 on the second would confirm the id exists and turn
    identifier guessing into tenant enumeration."""
    theirs = Survey.objects.create(organization=other_org, name="Theirs", slug="t")
    admin = member_factory(org, OrgRole.ADMIN)
    client = as_user(admin)

    forbidden = client.get(f"/api/v1/surveys/{theirs.id}/")
    missing = client.get(f"/api/v1/surveys/{uuid.uuid7()}/")

    assert forbidden.status_code == missing.status_code == 404


def test_a_respondent_token_grants_nothing_on_the_staff_api(respondent, live_survey):
    client, _ = respondent

    assert client.get(f"/api/v1/versions/{live_survey.id}/results/").status_code in (401, 403)


def test_a_staff_session_does_not_bypass_the_resume_token(
    as_user, live_survey, member_factory, ids
):
    """The two authentication paths are deliberately separate: being an org
    admin does not let you edit someone's in-progress draft."""
    submission = start_submission(live_survey)
    admin = member_factory(live_survey.survey.organization, OrgRole.ADMIN)

    response = as_user(admin).patch(
        f"/api/v1/public/submissions/{submission.id}/",
        {"answers": {ids["country"]: "sa"}},
        format="json",
    )

    assert response.status_code == 403


def test_an_export_cannot_be_downloaded_across_tenants(
    as_user, live_survey, other_org, member_factory, ids
):
    submission = start_submission(live_survey)
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)
    export = Export.objects.create(survey_version=live_survey, include_pii=True)

    outsider = member_factory(other_org, OrgRole.OWNER)

    assert as_user(outsider).get(f"/api/v1/exports/{export.id}/download/").status_code == 404


# --- mass assignment ---------------------------------------------------------


def test_a_survey_cannot_be_created_into_another_organization(
    as_user, org, other_org, member_factory
):
    admin = member_factory(org, OrgRole.ADMIN)

    response = as_user(admin).post(
        f"/api/v1/organizations/{org.id}/surveys/",
        {"name": "Sneaky", "slug": "sneaky", "organization": str(other_org.id)},
        format="json",
    )

    assert response.status_code == 201
    assert Survey.objects.get(slug="sneaky").organization_id == org.id


def test_a_respondent_cannot_set_their_own_submission_status(respondent, ids):
    """Marking a draft completed without passing validation would skip
    required fields and the hidden-answer purge."""
    client, started = respondent

    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["country"]: "sa"}, "status": "completed"},
        format="json",
    )

    assert Submission.objects.get(id=started["id"]).status == Submission.Status.IN_PROGRESS


def test_a_respondent_cannot_mark_an_answer_unencrypted(respondent, ids):
    """is_encrypted is decided by the schema, never by the payload."""
    client, started = respondent

    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["national_id"]: "1234567890"}, "is_encrypted": False},
        format="json",
    )

    assert Answer.objects.get(field_id=ids["national_id"]).is_encrypted is True


def test_a_version_cannot_be_published_by_patching_its_status(as_user, draft, member_factory):
    admin = member_factory(draft.survey.organization, OrgRole.ADMIN)

    as_user(admin).patch(f"/api/v1/versions/{draft.id}/", {"status": "published"}, format="json")

    draft.refresh_from_db()
    assert draft.status == SurveyVersion.Status.DRAFT


# --- data exposure -----------------------------------------------------------


def test_validation_errors_do_not_echo_a_sensitive_value(respondent, ids):
    """DRF normally reflects the offending input. For an encrypted field that
    would put the plaintext straight into a log aggregator."""
    client, started = respondent

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["national_id"]: 12345, ids["age"]: "not-a-number"}},
        format="json",
    )

    assert response.status_code == 400
    assert "12345" not in response.content.decode()


def test_ciphertext_is_never_returned_to_a_respondent(respondent, ids):
    client, started = respondent
    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["national_id"]: "1234567890"}},
        format="json",
    )

    body = client.get(f"/api/v1/public/submissions/{started['id']}/").json()
    stored = Answer.objects.get(field_id=ids["national_id"]).value

    assert body["answers"][ids["national_id"]] is None
    assert stored not in response_text(body)


def response_text(body) -> str:
    import json

    return json.dumps(body)


def test_resume_tokens_are_not_listed_to_staff(as_user, live_survey, member_factory, grant, ids):
    submission = start_submission(live_survey)
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)
    analyst = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(analyst, live_survey.survey, SurveyRole.ANALYST)

    body = as_user(analyst).get(f"/api/v1/versions/{live_survey.id}/submissions/").json()

    assert "resume_token" not in response_text(body)


# --- payload abuse -----------------------------------------------------------


def test_a_deeply_nested_payload_is_rejected_not_hung(respondent, ids):
    client, started = respondent
    nested = "x"
    for _ in range(60):
        nested = {"a": nested}

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        # country first, so the section holding comments is visible and the
        # value is actually validated rather than silently skipped.
        {"answers": {ids["country"]: "sa", ids["comments"]: nested}},
        format="json",
    )

    assert response.status_code == 400


def test_an_oversized_text_answer_is_rejected(respondent, ids):
    client, started = respondent
    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["country"]: "sa"}},
        format="json",
    )

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["comments"]: "x" * 100_000}},
        format="json",
    )

    assert response.status_code == 400


def test_unknown_fields_in_a_batch_are_rejected(respondent):
    client, started = respondent

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {str(uuid.uuid7()): "x"}},
        format="json",
    )

    assert response.status_code == 400


# --- rate limiting -----------------------------------------------------------


def test_starting_submissions_is_rate_limited(api, live_survey, monkeypatch):
    """Anonymous endpoints need a ceiling, or one script can fill a survey
    with noise and a database with rows.

    THROTTLE_RATES is bound as a class attribute when DRF imports, so
    override_settings cannot reach it -- the class is patched directly.
    """
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(
        ScopedRateThrottle,
        "THROTTLE_RATES",
        {"submission_start": "3/hour", "submission_write": "3/hour"},
    )
    cache.clear()

    codes = [
        api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").status_code
        for _ in range(5)
    ]

    assert codes.count(201) == 3
    assert codes.count(429) == 2
