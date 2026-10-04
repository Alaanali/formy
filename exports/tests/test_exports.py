import csv

import pytest
from auditlog.models import LogEntry
from django.core.files.storage import default_storage
from rest_framework.test import APIClient

from accounts.models import Membership
from exports.models import Export
from exports.tasks import REDACTED, generate_export
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


@pytest.fixture
def responses_present(live_survey, ids):
    for country, age in (("eg", 30), ("sa", 18)):
        submission = start_submission(live_survey)
        answers = {ids["country"]: country, ids["age"]: age, ids["national_id"]: "1234567890"}
        save_answers(submission, answers, complete=True)
    return live_survey


def read_csv(export):
    with default_storage.open(export.file_path) as handle:
        return list(csv.reader(handle.read().decode().splitlines()))


# --- generation --------------------------------------------------------------


def test_export_writes_one_row_per_completed_response(responses_present, analyst):
    export = Export.objects.create(
        survey_version=responses_present, requested_by=analyst, include_pii=True
    )
    generate_export.delay(str(export.id)).get()

    export.refresh_from_db()
    assert export.status == Export.Status.READY
    assert export.row_count == 2
    assert len(read_csv(export)) == 3  # header plus two rows


def test_incomplete_submissions_are_excluded(responses_present, analyst, ids):
    start_submission(responses_present)  # left in progress

    export = Export.objects.create(survey_version=responses_present, requested_by=analyst)
    generate_export.delay(str(export.id)).get()

    export.refresh_from_db()
    assert export.row_count == 2


def test_columns_are_labelled_from_the_schema(responses_present, analyst):
    export = Export.objects.create(survey_version=responses_present, requested_by=analyst)
    generate_export.delay(str(export.id)).get()

    export.refresh_from_db()
    header = read_csv(export)[0]

    assert header[:2] == ["submission_id", "submitted_at"]
    assert "Country" in header
    assert "National ID" in header


def test_pii_is_decrypted_only_when_the_export_allows_it(responses_present, analyst):
    allowed = Export.objects.create(
        survey_version=responses_present, requested_by=analyst, include_pii=True
    )
    generate_export.delay(str(allowed.id)).get()
    allowed.refresh_from_db()

    assert any("1234567890" in cell for row in read_csv(allowed) for cell in row)


def test_pii_is_redacted_when_the_export_does_not(responses_present, analyst):
    restricted = Export.objects.create(
        survey_version=responses_present, requested_by=analyst, include_pii=False
    )
    generate_export.delay(str(restricted.id)).get()
    restricted.refresh_from_db()

    rows = read_csv(restricted)
    assert not any("1234567890" in cell for row in rows for cell in row)
    assert any(REDACTED in cell for row in rows for cell in row)


def test_a_failed_export_records_why(responses_present, analyst, monkeypatch):
    """A failure has to be visible to whoever asked for the file, not just
    in a worker log they cannot read."""

    def boom(_version):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr("exports.tasks.get_document", boom)
    export = Export.objects.create(survey_version=responses_present, requested_by=analyst)

    with pytest.raises(RuntimeError):
        generate_export.delay(str(export.id)).get()

    export.refresh_from_db()
    assert export.status == Export.Status.FAILED
    assert "storage unavailable" in export.error
    assert export.completed_at is not None


# --- API ---------------------------------------------------------------------


def test_an_analyst_can_request_an_export(as_user, responses_present, analyst):
    response = as_user(analyst).post(
        f"/api/v1/versions/{responses_present.id}/exports/", format="json"
    )

    assert response.status_code == 201
    assert response.json()["include_pii"] is True
    assert response.json()["status"] == "ready"  # eager in tests


def test_a_viewer_cannot_request_an_export(as_user, responses_present, viewer):
    response = as_user(viewer).post(
        f"/api/v1/versions/{responses_present.id}/exports/", format="json"
    )

    assert response.status_code == 403


def test_pii_inclusion_follows_the_requesters_capability(
    as_user, responses_present, member_factory, grant
):
    """An org admin has the PII capability; a survey-scoped editor does not,
    and would get a redacted file if they could export at all."""
    admin = member_factory(responses_present.survey.organization, OrgRole.ADMIN)

    response = as_user(admin).post(
        f"/api/v1/versions/{responses_present.id}/exports/", format="json"
    )

    assert response.json()["include_pii"] is True


def test_requesting_an_export_is_audited(as_user, responses_present, analyst):
    as_user(analyst).post(f"/api/v1/versions/{responses_present.id}/exports/", format="json")

    entries = [
        e
        for e in LogEntry.objects.filter(action=LogEntry.Action.ACCESS)
        if (e.additional_data or {}).get("event") == "export.create"
    ]
    assert entries
    assert entries[0].actor == analyst


def test_downloading_returns_the_file(as_user, responses_present, analyst):
    created = (
        as_user(analyst)
        .post(f"/api/v1/versions/{responses_present.id}/exports/", format="json")
        .json()
    )

    response = as_user(analyst).get(f"/api/v1/exports/{created['id']}/download/")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"


def test_downloading_an_unfinished_export_is_a_conflict(as_user, responses_present, analyst):
    export = Export.objects.create(survey_version=responses_present, requested_by=analyst)

    response = as_user(analyst).get(f"/api/v1/exports/{export.id}/download/")

    assert response.status_code == 409


def test_exports_of_an_invisible_survey_are_404(as_user, responses_present, member_factory):
    outsider = member_factory(responses_present.survey.organization, OrgRole.MEMBER)

    response = as_user(outsider).get(f"/api/v1/versions/{responses_present.id}/exports/")

    assert response.status_code == 404
