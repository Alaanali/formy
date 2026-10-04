import pytest
from django.core import mail
from rest_framework.test import APIClient

from accounts.models import Membership
from invitations.models import Invitation, InvitationBatch, hash_recipient
from invitations.services import InvitationError, create_batch, redeem
from invitations.tasks import send_batch
from responses.models import Submission
from responses.services import save_answers
from surveys.models import SurveyAccess

pytestmark = pytest.mark.django_db
OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole


@pytest.fixture
def analyst(live_survey, member_factory, grant):
    user = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(user, live_survey.survey, SurveyRole.ANALYST)
    return user


@pytest.fixture
def api(analyst):
    client = APIClient()
    client.force_authenticate(user=analyst)
    return client


# --- anonymity ----------------------------------------------------------------


def test_the_address_is_never_stored(live_survey):
    """The platform's premise is that respondents are anonymous. A plaintext
    email beside their answers would undo that in one column."""
    batch = create_batch(live_survey, ["Alice@Example.com"])

    invitation = Invitation.objects.get(batch=batch)
    assert "alice" not in invitation.recipient_hash.lower()
    assert "@" not in invitation.recipient_hash
    assert invitation.recipient_hash == hash_recipient("alice@example.com")


def test_the_hash_is_keyed_so_it_cannot_be_checked_offline(live_survey, settings):
    """An unkeyed hash of an email is reversible by anyone with a list of
    addresses -- the domain is far too small."""
    first = hash_recipient("alice@example.com")
    settings.SECRET_KEY = "a-completely-different-secret"
    assert hash_recipient("alice@example.com") != first


def test_addresses_are_normalised_so_one_person_gets_one_invitation(live_survey):
    batch = create_batch(live_survey, [" Alice@Example.com ", "alice@example.com"])

    assert batch.total == 1
    assert Invitation.objects.filter(batch=batch).count() == 1


def test_the_link_carries_no_identity(live_survey):
    batch = create_batch(live_survey, ["alice@example.com"])
    token = Invitation.objects.get(batch=batch).token

    # The token identifies the invitation, not the person.
    assert "alice" not in token.lower()
    assert len(token) >= 40


# --- one response per invitee --------------------------------------------------


def test_redeeming_twice_returns_the_same_draft(live_survey):
    """Clicking the emailed link again must not open a second response."""
    batch = create_batch(live_survey, ["alice@example.com"])
    token = Invitation.objects.get(batch=batch).token

    first = redeem(token)
    second = redeem(token)

    assert first.id == second.id
    assert Submission.objects.count() == 1


def test_a_completed_invitation_cannot_be_reopened(live_survey, ids):
    batch = create_batch(live_survey, ["alice@example.com"])
    token = Invitation.objects.get(batch=batch).token

    submission = redeem(token)
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)

    with pytest.raises(InvitationError, match="already been completed"):
        redeem(token)


def test_re_sending_to_an_overlapping_list_grants_no_second_response(live_survey):
    """A client re-uploading their list should not be punished for the
    overlap, and must not hand anyone a second response."""
    first = create_batch(live_survey, ["alice@example.com", "bob@example.com"])
    token = Invitation.objects.get(
        batch=first, recipient_hash=hash_recipient("alice@example.com")
    ).token

    second = create_batch(live_survey, ["alice@example.com", "carol@example.com"])

    assert Invitation.objects.filter(survey_version=live_survey).count() == 3
    # Alice keeps her original invitation, and her original link still works.
    assert redeem(token).id is not None
    assert second.total == 2


def test_an_unknown_token_is_refused(live_survey):
    with pytest.raises(InvitationError, match="not valid"):
        redeem("not-a-real-token")


def test_an_expired_invitation_is_refused(live_survey):
    from datetime import timedelta

    from django.utils import timezone

    batch = create_batch(live_survey, ["alice@example.com"])
    invitation = Invitation.objects.get(batch=batch)
    Invitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    with pytest.raises(InvitationError, match="expired"):
        redeem(invitation.token)


def test_only_a_published_version_can_be_sent(draft):
    with pytest.raises(InvitationError, match="published"):
        create_batch(draft, ["alice@example.com"])


# --- sending ------------------------------------------------------------------


def test_the_batch_sends_on_the_queue(live_survey):
    batch = create_batch(live_survey, ["a@example.com", "b@example.com"])

    result = send_batch.delay(str(batch.id)).get()

    assert result == {"sent": 2}
    batch.refresh_from_db()
    assert batch.status == InvitationBatch.Status.SENT
    assert len(mail.outbox) == 2


def test_the_email_carries_the_invitation_link(live_survey):
    batch = create_batch(live_survey, ["a@example.com"])
    send_batch.delay(str(batch.id)).get()

    token = Invitation.objects.get(batch=batch).token
    assert token in mail.outbox[0].body
    assert live_survey.survey.name in mail.outbox[0].subject


def test_a_retry_resumes_rather_than_mailing_everyone_again(live_survey):
    """A naive retry after a partial failure is worse than no retry."""
    batch = create_batch(live_survey, ["a@example.com", "b@example.com"])
    send_batch.delay(str(batch.id)).get()
    assert len(mail.outbox) == 2

    send_batch.delay(str(batch.id)).get()

    assert len(mail.outbox) == 2  # nothing re-sent


# --- API ----------------------------------------------------------------------


def test_an_analyst_can_invite(api, live_survey):
    response = api.post(
        f"/api/v1/versions/{live_survey.id}/invitations/",
        {"recipients": ["a@example.com", "b@example.com"]},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["total"] == 2


def test_a_viewer_cannot_invite(live_survey, member_factory, grant):
    viewer = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(viewer, live_survey.survey, SurveyRole.VIEWER)
    client = APIClient()
    client.force_authenticate(user=viewer)

    response = client.post(
        f"/api/v1/versions/{live_survey.id}/invitations/",
        {"recipients": ["a@example.com"]},
        format="json",
    )

    assert response.status_code == 403


def test_sending_is_audited(api, live_survey):
    from auditlog.models import LogEntry

    api.post(
        f"/api/v1/versions/{live_survey.id}/invitations/",
        {"recipients": ["a@example.com"]},
        format="json",
    )

    entries = [
        e
        for e in LogEntry.objects.filter(action=LogEntry.Action.ACCESS)
        if (e.additional_data or {}).get("event") == "invitation.send"
    ]
    assert entries
    assert entries[0].additional_data["recipients"] == 1


def test_redeeming_over_http_returns_a_usable_submission(live_survey):
    batch = create_batch(live_survey, ["a@example.com"])
    token = Invitation.objects.get(batch=batch).token

    anonymous = APIClient()
    response = anonymous.post(f"/api/v1/public/invitations/{token}/redeem/")

    assert response.status_code == 200
    body = response.json()
    assert body["resume_token"]

    # The same shape as starting directly, so the client has one path.
    anonymous.credentials(HTTP_X_RESUME_TOKEN=body["resume_token"])
    assert anonymous.get(f"/api/v1/public/submissions/{body['id']}/").status_code == 200


def test_an_invalid_token_over_http_is_a_400_not_a_crash(live_survey):
    assert APIClient().post("/api/v1/public/invitations/nope/redeem/").status_code == 400
