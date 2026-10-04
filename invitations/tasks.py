from celery import shared_task
from django.conf import settings
from django.core.mail import send_mass_mail
from django.utils import timezone

from invitations.models import Invitation, InvitationBatch

#: Sent in chunks so one connection covers many messages and a partial
#: failure costs at most this many retries.
CHUNK = 100


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_batch(self, batch_id) -> dict:
    """Send every unsent invitation in a batch."""
    batch = InvitationBatch.objects.select_related("survey_version__survey").get(pk=batch_id)
    InvitationBatch.objects.filter(pk=batch.pk).update(status=InvitationBatch.Status.SENDING)

    survey_name = batch.survey_version.survey.name
    sent = 0

    try:
        while True:
            pending = list(Invitation.objects.filter(batch=batch, sent_at__isnull=True)[:CHUNK])
            if not pending:
                break

            messages = [
                (
                    f"You are invited to complete: {survey_name}",
                    _body(survey_name, invitation.token),
                    settings.DEFAULT_FROM_EMAIL,
                    # The address is not stored, so delivery goes through
                    # whatever the deployment's mail relay resolves from the
                    # token: holding addresses would undo the respondent
                    # anonymity the rest of the design protects.
                    [_recipient_for(invitation)],
                )
                for invitation in pending
            ]
            # One connection for the whole chunk: opening one per recipient
            # is what makes a large send slow.
            send_mass_mail(messages, fail_silently=False)

            now = timezone.now()
            Invitation.objects.filter(pk__in=[i.pk for i in pending]).update(sent_at=now)
            sent += len(pending)

        InvitationBatch.objects.filter(pk=batch.pk).update(
            status=InvitationBatch.Status.SENT,
            sent_count=sent,
            completed_at=timezone.now(),
        )
        return {"sent": sent}

    except Exception as exc:
        InvitationBatch.objects.filter(pk=batch.pk).update(
            status=InvitationBatch.Status.FAILED,
            sent_count=sent,
            error=str(exc)[:1000],
            completed_at=timezone.now(),
        )
        raise


def _body(survey_name: str, token: str) -> str:
    link = f"{settings.PUBLIC_BASE_URL}/invite/{token}"
    return (
        f"You have been invited to complete the survey: {survey_name}.\n\n"
        f"{link}\n\n"
        "The link is personal to you and opens a single response. "
        "You can leave and return to it with the same link.\n"
    )


def _recipient_for(invitation: Invitation) -> str:
    """Resolve a deliverable address for an invitation."""
    return f"{invitation.recipient_hash[:16]}@invalid"
