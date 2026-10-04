import pytest
from rest_framework.test import APIClient

from responses.models import Submission
from responses.permissions import RESUME_TOKEN_HEADER

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def started(api, live_survey):
    response = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/")
    assert response.status_code == 201
    return response.json()


def with_token(api, token):
    api.credentials(**{f"HTTP_{RESUME_TOKEN_HEADER.upper().replace('-', '_')}": token})
    return api


# --- starting ----------------------------------------------------------------


def test_anyone_can_start_a_submission(api, live_survey):
    response = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/")

    assert response.status_code == 201
    assert response.json()["status"] == "in_progress"
    assert response.json()["resume_token"]


def test_a_draft_version_cannot_be_answered(api, draft):
    assert api.post(f"/api/v1/public/versions/{draft.id}/submissions/").status_code == 404


# --- the token is the whole authorization story ------------------------------


def test_reading_without_a_token_is_rejected(api, started):
    assert api.get(f"/api/v1/public/submissions/{started['id']}/").status_code == 403


def test_reading_with_the_wrong_token_is_rejected(api, started):
    client = with_token(api, "not-the-token")

    assert client.get(f"/api/v1/public/submissions/{started['id']}/").status_code == 403


def test_another_submissions_token_does_not_work(api, live_survey, started):
    other = api.post(f"/api/v1/public/versions/{live_survey.id}/submissions/").json()
    client = with_token(api, other["resume_token"])

    assert client.get(f"/api/v1/public/submissions/{started['id']}/").status_code == 403


def test_an_expired_draft_cannot_be_resumed(api, started):
    from datetime import timedelta

    from django.utils import timezone

    Submission.objects.filter(id=started["id"]).update(
        resume_expires_at=timezone.now() - timedelta(days=1)
    )
    client = with_token(api, started["resume_token"])

    assert client.get(f"/api/v1/public/submissions/{started['id']}/").status_code == 403


def test_the_resume_token_is_never_echoed_on_a_read(api, started):
    """It is a bearer credential: returned once at creation, never again."""
    client = with_token(api, started["resume_token"])

    body = client.get(f"/api/v1/public/submissions/{started['id']}/").json()

    assert "resume_token" not in body


def test_the_token_travels_in_a_header_not_the_url(api, started):
    """A credential in a path ends up in access logs, proxy logs and Referer
    headers. The URL carries only the submission id."""
    assert started["resume_token"] not in f"/api/v1/public/submissions/{started['id']}/"


# --- state payload -----------------------------------------------------------


def test_state_includes_server_resolved_visibility(api, started, ids):
    client = with_token(api, started["resume_token"])

    body = client.get(f"/api/v1/public/submissions/{started['id']}/").json()

    assert body["visible"][ids["country"]] is True
    assert body["visible"][ids["city"]] is False  # section gated on country


def test_state_includes_filtered_options(api, started, ids):
    client = with_token(api, started["resume_token"])
    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["country"]: "sa"}},
        format="json",
    )

    body = client.get(f"/api/v1/public/submissions/{started['id']}/").json()

    assert body["options"][ids["city"]] == ["riyadh"]


def test_state_hides_sensitive_answers(api, started, ids):
    client = with_token(api, started["resume_token"])
    client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["national_id"]: "1234567890"}},
        format="json",
    )

    body = client.get(f"/api/v1/public/submissions/{started['id']}/").json()

    assert body["answers"][ids["national_id"]] is None


# --- autosave and submit -----------------------------------------------------


def test_autosave_persists_a_partial_batch(api, started, ids):
    client = with_token(api, started["resume_token"])

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["country"]: "sa"}},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["answers"][ids["country"]] == "sa"


def test_autosave_does_not_enforce_required_fields(api, started, ids):
    """Half-filled forms must save, or resume is pointless."""
    client = with_token(api, started["resume_token"])

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["age"]: 30}},
        format="json",
    )

    assert response.status_code == 200


def test_invalid_answers_return_per_field_errors(api, started, ids):
    client = with_token(api, started["resume_token"])

    response = client.patch(
        f"/api/v1/public/submissions/{started['id']}/",
        {"answers": {ids["age"]: 500}},
        format="json",
    )

    assert response.status_code == 400
    assert "at most 120" in response.json()["errors"][ids["age"]]


def test_submitting_enforces_required_fields(api, started, ids):
    client = with_token(api, started["resume_token"])

    response = client.post(
        f"/api/v1/public/submissions/{started['id']}/submit/", {"answers": {}}, format="json"
    )

    assert response.status_code == 400
    assert "required" in response.json()["errors"][ids["country"]]


def test_a_full_journey(api, started, ids):
    client = with_token(api, started["resume_token"])
    url = f"/api/v1/public/submissions/{started['id']}/"

    client.patch(url, {"answers": {ids["country"]: "sa", ids["age"]: 30}}, format="json")
    client.patch(url, {"answers": {ids["city"]: "riyadh"}}, format="json")
    response = client.post(f"{url}submit/", {"answers": {}}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_resuming_returns_previously_saved_answers(api, started, ids):
    client = with_token(api, started["resume_token"])
    url = f"/api/v1/public/submissions/{started['id']}/"
    client.patch(url, {"answers": {ids["country"]: "sa"}}, format="json")

    fresh = with_token(APIClient(), started["resume_token"])
    body = fresh.get(url).json()

    assert body["answers"][ids["country"]] == "sa"


def test_a_completed_submission_can_no_longer_be_resumed(api, started, ids):
    client = with_token(api, started["resume_token"])
    url = f"/api/v1/public/submissions/{started['id']}/"
    client.patch(url, {"answers": {ids["country"]: "eg", ids["age"]: 30}}, format="json")
    client.post(f"{url}submit/", {"answers": {}}, format="json")

    assert client.get(url).status_code == 403


def test_a_crafted_answer_to_a_hidden_field_is_ignored(api, started, ids):
    """The client cannot talk the server into storing something the logic
    says the respondent was never shown."""
    client = with_token(api, started["resume_token"])
    url = f"/api/v1/public/submissions/{started['id']}/"

    response = client.patch(
        url, {"answers": {ids["country"]: "eg", ids["city"]: "cairo"}}, format="json"
    )

    assert response.status_code == 200
    assert ids["city"] not in response.json()["answers"]


def test_ip_is_stored_hashed_not_raw(api, live_survey):
    """Keeping the raw address would de-anonymise a respondent we
    deliberately created no account for."""
    response = api.post(
        f"/api/v1/public/versions/{live_survey.id}/submissions/", REMOTE_ADDR="203.0.113.7"
    )

    submission = Submission.objects.get(id=response.json()["id"])
    assert "203.0.113.7" not in str(submission.meta)
    assert submission.meta["ip_hash"]


def test_respondent_endpoints_do_not_advertise_the_staff_auth_scheme(api, started):
    """Adding TokenAuthentication project-wide briefly made these answer 401
    with WWW-Authenticate: Token -- pointing an anonymous respondent at a
    staff login scheme that cannot help them. The two authentication paths
    are deliberately separate."""
    response = api.get(f"/api/v1/public/submissions/{started['id']}/")

    assert response.status_code == 403
    assert "WWW-Authenticate" not in response
