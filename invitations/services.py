from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from invitations.models import Invitation, InvitationBatch, hash_recipient
from responses.models import Submission
from surveys.models import SurveyVersion


class InvitationError(Exception):
    """The invitation cannot be used. The message reaches the respondent."""


@transaction.atomic
def create_batch(
    version: SurveyVersion, recipients: list[str], *, requested_by=None
) -> InvitationBatch:
    """Record a send."""
    if version.status != SurveyVersion.Status.PUBLISHED:
        raise InvitationError("Only a published version can be sent out.")

    batch = InvitationBatch.objects.create(
        survey_version=version, requested_by=requested_by, total=len(recipients)
    )

    window = timedelta(days=settings.INVITATION_WINDOW_DAYS)
    expires = timezone.now() + window

    # Deduplicated within the batch too: the same address twice in one
    # upload is a list-hygiene problem, not an entitlement to two responses.
    seen: set[str] = set()
    rows = []
    for address in recipients:
        digest = hash_recipient(address)
        if digest in seen:
            continue
        seen.add(digest)
        rows.append(
            Invitation(
                batch=batch,
                survey_version=version,
                recipient_hash=digest,
                expires_at=expires,
            )
        )

    # ignore_conflicts, so a re-send to an overlapping list keeps the
    # original invitation -- and the original token -- rather than failing
    # the whole batch on the unique constraint.
    Invitation.objects.bulk_create(rows, ignore_conflicts=True)

    batch.total = len(seen)
    batch.save(update_fields=["total"])
    return batch


def redeem(token: str) -> Submission:
    """Exchange an invitation token for its submission."""
    from responses.services import start_submission

    invitation = (
        Invitation.objects.select_related("survey_version", "submission")
        .filter(token=token)
        .first()
    )
    if invitation is None:
        raise InvitationError("This invitation link is not valid.")

    if invitation.expires_at and invitation.expires_at < timezone.now():
        raise InvitationError("This invitation has expired.")

    if invitation.submission_id:
        if invitation.submission.status == Submission.Status.COMPLETED:
            raise InvitationError("This survey has already been completed.")
        return invitation.submission

    with transaction.atomic():
        # Locked, so two clicks in flight cannot both pass the None check
        # above and open two submissions.
        locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if locked.submission_id:
            return locked.submission

        submission = start_submission(locked.survey_version)
        locked.submission = submission
        locked.save(update_fields=["submission"])

    return submission
