import uuid
from datetime import timedelta

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone

from responses.models import Answer, Submission
from surveys.models import Section
from surveys.publish import publish
from surveys.tests.factories import choice, fid


@pytest.fixture
def published(draft):
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={fid(): choice()})
    return publish(draft)


@pytest.fixture
def submission(published):
    return Submission.objects.create(survey_version=published)


# --- submission --------------------------------------------------------------


@pytest.mark.django_db
def test_submission_starts_in_progress_with_a_resume_token(submission):
    assert submission.status == Submission.Status.IN_PROGRESS
    assert submission.resume_token
    assert submission.submitted_at is None


@pytest.mark.django_db
def test_resume_tokens_are_unguessable_and_unique(published):
    """The token is the only credential protecting an anonymous draft, so its
    entropy is load-bearing rather than cosmetic."""
    tokens = {Submission.objects.create(survey_version=published).resume_token for _ in range(20)}

    assert len(tokens) == 20
    assert all(len(t) >= 40 for t in tokens)


@pytest.mark.django_db
def test_resume_token_is_unique_across_submissions(published):
    first = Submission.objects.create(survey_version=published)
    with pytest.raises(IntegrityError):
        Submission.objects.create(survey_version=published, resume_token=first.resume_token)


@pytest.mark.django_db
def test_expired_draft_is_not_resumable(submission):
    submission.resume_expires_at = timezone.now() - timedelta(hours=1)
    assert submission.is_resumable is False

    submission.resume_expires_at = timezone.now() + timedelta(hours=1)
    assert submission.is_resumable is True


@pytest.mark.django_db
def test_completed_submission_is_not_resumable(submission):
    submission.status = Submission.Status.COMPLETED
    assert submission.is_resumable is False


@pytest.mark.django_db
def test_published_version_cannot_be_deleted_while_responses_exist(published, submission):
    """PROTECT, so history cannot be destroyed by removing the schema that
    gives it meaning."""
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        published.delete()


@pytest.mark.django_db
def test_submission_has_no_respondent_field():
    """Respondents are anonymous; no auth record is created for them."""
    assert not any(f.name == "respondent" for f in Submission._meta.get_fields())


# --- answers -----------------------------------------------------------------


@pytest.mark.django_db
def test_one_answer_per_field_per_submission(submission):
    field_id = uuid.uuid7()
    Answer.objects.create(submission=submission, field_id=field_id, value="first")

    with pytest.raises(IntegrityError):
        Answer.objects.create(submission=submission, field_id=field_id, value="second")


@pytest.mark.django_db
def test_the_unique_constraint_makes_autosave_an_upsert(submission):
    field_id = uuid.uuid7()
    Answer.objects.update_or_create(
        submission=submission, field_id=field_id, defaults={"value": "typing"}
    )
    Answer.objects.update_or_create(
        submission=submission, field_id=field_id, defaults={"value": "typing more"}
    )

    assert submission.answers.count() == 1
    assert submission.answers.get().value == "typing more"


@pytest.mark.django_db
def test_two_submissions_may_answer_the_same_field(published):
    field_id = uuid.uuid7()
    a = Submission.objects.create(survey_version=published)
    b = Submission.objects.create(survey_version=published)

    Answer.objects.create(submission=a, field_id=field_id, value="x")
    Answer.objects.create(submission=b, field_id=field_id, value="y")

    assert Answer.objects.filter(field_id=field_id).count() == 2


@pytest.mark.django_db
def test_answers_are_removed_with_their_submission(submission):
    Answer.objects.create(submission=submission, field_id=uuid.uuid7(), value="x")
    submission.delete()

    assert Answer.objects.count() == 0


@pytest.mark.django_db
def test_field_id_is_stored_as_a_uuid_not_text(submission):
    """16 bytes natively rather than 36 characters, and type-checked."""
    field = Answer._meta.get_field("field_id")
    assert field.get_internal_type() == "UUIDField"
