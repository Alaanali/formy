import uuid

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from responses.models import SubmissionFile
from responses.permissions import RESUME_TOKEN_HEADER
from responses.services import AnswerValidationError, save_answers, start_submission
from responses.uploads import UploadRejected, max_upload_bytes, store_upload
from surveys.document import FieldType
from surveys.models import Section
from surveys.publish import publish
from surveys.tests.factories import choice

pytestmark = pytest.mark.django_db

CV = str(uuid.uuid7())
COUNTRY = str(uuid.uuid7())


@pytest.fixture
def file_survey(draft):
    Section.objects.create(
        version=draft,
        key="apply",
        title="Apply",
        order=1,
        content={
            COUNTRY: choice(values=("sa", "eg"), label="Country", required=True),
            CV: {"type": FieldType.FILE, "key": "cv", "label": "Your CV"},
        },
    )
    return publish(draft)


@pytest.fixture
def submission(file_survey):
    return start_submission(file_survey)


def pdf(name="cv.pdf", size=128):
    return SimpleUploadedFile(name, b"%PDF-1.4" + b"x" * size, content_type="application/pdf")


# --- storing -----------------------------------------------------------------


def test_an_upload_is_stored_with_its_metadata(submission):
    record = store_upload(submission, CV, pdf())

    assert record.size_bytes > 0
    assert record.content_type == "application/pdf"
    assert default_storage.exists(record.storage_key)


def test_the_filename_never_reaches_the_storage_path(submission):
    """A name is display metadata. Putting it in the path invites traversal
    and collisions between respondents."""
    record = store_upload(submission, CV, pdf(name="../../etc/passwd"))

    assert ".." not in record.storage_key
    assert str(record.id) in record.storage_key
    assert record.original_name == "passwd"


def test_a_file_for_a_non_file_field_is_refused(submission):
    with pytest.raises(UploadRejected, match="does not accept a file"):
        store_upload(submission, COUNTRY, pdf())


def test_a_file_for_an_unknown_field_is_refused(submission):
    with pytest.raises(UploadRejected, match="Unknown field"):
        store_upload(submission, str(uuid.uuid7()), pdf())


def test_an_unsupported_type_is_refused(submission):
    """An allowlist, not a denylist: a denylist is a guessing game."""
    nasty = SimpleUploadedFile("x.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml")

    with pytest.raises(UploadRejected, match="not accepted"):
        store_upload(submission, CV, nasty)


@pytest.mark.parametrize(("size", "accepted"), [(2048, True), (2049, False)])
def test_the_size_ceiling_is_enforced_exactly(submission, settings, size, accepted):
    """Pinned to a known limit on both sides. Deriving the payload from the
    constant -- b"x" * (LIMIT + 1) -- passes for any ceiling, including one
    that is wrong or ignored."""
    settings.MAX_UPLOAD_BYTES = 2048
    assert max_upload_bytes() == 2048  # read lazily, so override works

    upload = SimpleUploadedFile("f.pdf", b"x" * size, content_type="application/pdf")

    if accepted:
        assert store_upload(submission, CV, upload).size_bytes == size
    else:
        with pytest.raises(UploadRejected, match="limit is 2048"):
            store_upload(submission, CV, upload)


# --- answering with it --------------------------------------------------------


def test_the_returned_id_is_accepted_as_the_answer(submission):
    record = store_upload(submission, CV, pdf())

    save_answers(submission, {COUNTRY: "sa", CV: str(record.id)}, complete=True)

    submission.refresh_from_db()
    assert submission.status == "completed"


def test_an_answer_naming_no_upload_is_refused(submission):
    with pytest.raises(AnswerValidationError) as caught:
        save_answers(submission, {CV: str(uuid.uuid7())})

    assert "no such upload" in caught.value.errors[CV]


def test_an_answer_cannot_claim_another_respondents_upload(file_survey, submission):
    """Without scoping the lookup to the submission, anyone could attach
    somebody else's file to their own response by guessing an id."""
    theirs = store_upload(start_submission(file_survey), CV, pdf())

    with pytest.raises(AnswerValidationError) as caught:
        save_answers(submission, {CV: str(theirs.id)})

    assert "no such upload" in caught.value.errors[CV]


def test_uploads_for_hidden_fields_are_deleted_at_submission(
    draft, django_capture_on_commit_callbacks
):
    """A file behind a question the logic ended up hiding is personal data
    nobody asked for and nothing will ever read."""
    gated_cv = str(uuid.uuid7())
    Section.objects.create(
        version=draft,
        key="s1",
        title="One",
        order=1,
        content={COUNTRY: choice(values=("sa", "eg"), label="Country", required=True)},
    )
    Section.objects.create(
        version=draft,
        key="s2",
        title="Two",
        order=2,
        content={
            gated_cv: {
                "type": FieldType.FILE,
                "key": "cv",
                "label": "CV",
                "visible": {"all": [{"field": COUNTRY, "op": "eq", "value": "sa"}]},
            }
        },
    )
    version = publish(draft)
    submission = start_submission(version)

    save_answers(submission, {COUNTRY: "sa"})
    record = store_upload(submission, gated_cv, pdf())
    save_answers(submission, {gated_cv: str(record.id)})

    # Switching country hides that whole section. The bytes are unlinked on
    # commit, not inline: unlinking is not transactional, so a rollback would
    # otherwise restore the row and leave the file gone forever.
    with django_capture_on_commit_callbacks(execute=True):
        save_answers(submission, {COUNTRY: "eg"}, complete=True)

    assert not SubmissionFile.objects.filter(pk=record.pk).exists()
    assert not default_storage.exists(record.storage_key)


# --- the API ------------------------------------------------------------------


@pytest.fixture
def api(submission):
    client = APIClient()
    client.credentials(
        **{f"HTTP_{RESUME_TOKEN_HEADER.upper().replace('-', '_')}": submission.resume_token}
    )
    return client


def test_upload_endpoint_returns_an_id_to_answer_with(api, submission):
    response = api.post(
        f"/api/v1/public/submissions/{submission.id}/files/",
        {"field_id": CV, "file": pdf()},
        format="multipart",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_name"] == "cv.pdf"
    assert "storage_key" not in body  # an internal path, not the client's business


def test_upload_requires_the_resume_token(submission):
    anonymous = APIClient()

    response = anonymous.post(
        f"/api/v1/public/submissions/{submission.id}/files/",
        {"field_id": CV, "file": pdf()},
        format="multipart",
    )

    assert response.status_code == 403


def test_a_rejected_upload_explains_why(api, submission):
    response = api.post(
        f"/api/v1/public/submissions/{submission.id}/files/",
        {"field_id": COUNTRY, "file": pdf()},
        format="multipart",
    )

    assert response.status_code == 400
    assert "does not accept a file" in str(response.json())


def test_the_whole_journey_over_http(api, submission):
    uploaded = api.post(
        f"/api/v1/public/submissions/{submission.id}/files/",
        {"field_id": CV, "file": pdf()},
        format="multipart",
    ).json()

    saved = api.patch(
        f"/api/v1/public/submissions/{submission.id}/",
        {"answers": {COUNTRY: "sa", CV: uploaded["id"]}},
        format="json",
    )
    assert saved.status_code == 200

    done = api.post(
        f"/api/v1/public/submissions/{submission.id}/submit/", {"answers": {}}, format="json"
    )
    assert done.status_code == 200
    assert done.json()["status"] == "completed"


def test_a_rolled_back_submit_does_not_destroy_the_bytes(draft):
    """Unlinking a file cannot be rolled back, so it must not happen until
    the transaction that decided to has actually committed. Deleting inline
    meant a later failure restored the row and left the bytes gone, with
    storage backends swallowing the missing-key delete so nothing noticed."""
    from django.db import transaction

    gated = str(uuid.uuid7())
    Section.objects.create(
        version=draft,
        key="s1",
        title="One",
        order=1,
        content={COUNTRY: choice(values=("sa", "eg"), label="Country", required=True)},
    )
    Section.objects.create(
        version=draft,
        key="s2",
        title="Two",
        order=2,
        content={
            gated: {
                "type": FieldType.FILE,
                "key": "cv",
                "label": "CV",
                "visible": {"all": [{"field": COUNTRY, "op": "eq", "value": "sa"}]},
            }
        },
    )
    version = publish(draft)
    submission = start_submission(version)

    save_answers(submission, {COUNTRY: "sa"})
    record = store_upload(submission, gated, pdf())

    with pytest.raises(RuntimeError), transaction.atomic():
        save_answers(submission, {COUNTRY: "eg"}, complete=True)
        raise RuntimeError("something later in the request failed")

    # The row came back, so the bytes must still be there to match it.
    assert SubmissionFile.objects.filter(pk=record.pk).exists()
    assert default_storage.exists(record.storage_key)


def test_an_upload_for_a_hidden_field_is_refused(draft):
    """The answer path silently drops answers to hidden fields. The upload
    path must refuse them outright, or a respondent can write storage for a
    question the server says they were never shown -- bytes nothing will
    ever reference or reclaim."""
    gated = str(uuid.uuid7())
    Section.objects.create(
        version=draft,
        key="s1",
        title="One",
        order=1,
        content={COUNTRY: choice(values=("sa", "eg"), label="Country", required=True)},
    )
    Section.objects.create(
        version=draft,
        key="s2",
        title="Two",
        order=2,
        content={
            gated: {
                "type": FieldType.FILE,
                "key": "cv",
                "label": "CV",
                "visible": {"all": [{"field": COUNTRY, "op": "eq", "value": "sa"}]},
            }
        },
    )
    version = publish(draft)
    submission = start_submission(version)
    save_answers(submission, {COUNTRY: "eg"})  # hides the file field

    with pytest.raises(UploadRejected, match="not being asked of you"):
        store_upload(submission, gated, pdf())

    assert SubmissionFile.objects.filter(submission=submission).count() == 0


def test_a_malformed_upload_id_is_a_field_error_not_a_crash(submission):
    """Passing a client string into filter(pk=...) raised Django's
    ValidationError out of code contracted to return a message. It escaped as
    a whole-request 400, discarding every other field's error in the batch."""
    with pytest.raises(AnswerValidationError) as caught:
        save_answers(submission, {COUNTRY: "sa", CV: "not-a-uuid"})

    assert caught.value.errors[CV] == "no such upload for this submission"
    assert COUNTRY not in caught.value.errors  # the valid field survived


def test_an_upload_id_spelled_differently_still_matches(submission):
    """A UUID has several valid spellings; the client picks one and the
    schema may hold another."""
    record = store_upload(submission, CV, pdf())

    save_answers(submission, {COUNTRY: "sa", CV: str(record.id).upper()}, complete=True)

    submission.refresh_from_db()
    assert submission.status == "completed"


def test_the_storage_key_records_where_the_file_actually_landed(submission):
    """A backend with file_overwrite=False suffixes a collision, so keeping
    the requested key would leave the row pointing at nothing -- and a later
    delete would be a silent no-op."""
    record = store_upload(submission, CV, pdf())

    assert default_storage.exists(record.storage_key)


# --- download -----------------------------------------------------------------


@pytest.fixture
def staff_clients(submission, member_factory, grant):
    from accounts.models import Membership
    from surveys.models import SurveyAccess

    org = submission.survey_version.survey.organization
    survey = submission.survey_version.survey

    def client_for(role):
        user = member_factory(org, Membership.OrgRole.MEMBER)
        grant(user, survey, role)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return {
        "analyst": client_for(SurveyAccess.SurveyRole.ANALYST),
        "viewer": client_for(SurveyAccess.SurveyRole.VIEWER),
        "editor": client_for(SurveyAccess.SurveyRole.EDITOR),
    }


def test_a_file_from_another_tenant_is_404(submission, staff_clients, other_org, user_factory):
    from accounts.models import Membership

    record = store_upload(submission, CV, pdf())
    outsider = user_factory()
    Membership.objects.create(user=outsider, organization=other_org, role=Membership.OrgRole.OWNER)
    client = APIClient()
    client.force_authenticate(user=outsider)

    assert client.get(f"/api/v1/files/{record.id}/download/").status_code == 404


# --- encryption ---------------------------------------------------------------


def test_an_analyst_can_download_an_upload(submission, staff_clients):
    record = store_upload(submission, CV, pdf())

    response = staff_clients["analyst"].get(f"/api/v1/files/{record.id}/download/")

    assert response.status_code == 200
    assert b"%PDF" in b"".join(response.streaming_content)


def test_the_file_is_always_an_attachment_with_a_neutral_type(submission, staff_clients):
    """The stored content type is client-declared, so echoing it would turn
    an HTML file uploaded as image/png into stored XSS on this origin."""
    record = store_upload(submission, CV, pdf())

    response = staff_clients["analyst"].get(f"/api/v1/files/{record.id}/download/")

    assert response["Content-Type"] == "application/octet-stream"
    assert "attachment" in response["Content-Disposition"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_a_viewer_cannot_download(submission, staff_clients):
    """A filename alone routinely identifies the respondent, so this needs
    the PII capability rather than merely the right to read responses."""
    record = store_upload(submission, CV, pdf())

    assert staff_clients["viewer"].get(f"/api/v1/files/{record.id}/download/").status_code == 403
    assert staff_clients["editor"].get(f"/api/v1/files/{record.id}/download/").status_code == 403


def test_downloading_is_audited(submission, staff_clients):
    from auditlog.models import LogEntry

    record = store_upload(submission, CV, pdf())
    staff_clients["analyst"].get(f"/api/v1/files/{record.id}/download/")

    entries = [
        e
        for e in LogEntry.objects.filter(action=LogEntry.Action.ACCESS)
        if (e.additional_data or {}).get("file_id") == str(record.id)
    ]
    assert entries
    assert entries[0].additional_data["filename"] == "cv.pdf"
