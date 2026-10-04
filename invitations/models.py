import hashlib
import secrets

from django.conf import settings
from django.db import models

from core.models import UUIDModel
from surveys.models import SurveyVersion

TOKEN_BYTES = 32


def new_invite_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_recipient(address: str) -> str:
    """A recipient is stored hashed, never in the clear.

    Respondents are anonymous: no User row, hashed IP. A plaintext email
    beside their answers would undo that in one column. Keyed with
    SECRET_KEY so the hash cannot be tested against a candidate address, and
    normalised so the same person reached twice is one invitation.
    """
    normalised = address.strip().casefold().encode()
    return hashlib.blake2b(
        normalised, key=settings.SECRET_KEY.encode()[:64], digest_size=32
    ).hexdigest()


class InvitationBatch(UUIDModel):
    """One send of a survey to a list of people."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.CASCADE, related_name="invitation_batches"
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    total = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation batch {self.id} ({self.status})"


class Invitation(UUIDModel):
    """One person's invitation to one version of a survey."""

    batch = models.ForeignKey(InvitationBatch, on_delete=models.CASCADE, related_name="invitations")
    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.CASCADE, related_name="invitations"
    )

    #: Keyed hash of the address. The address itself is never stored.
    recipient_hash = models.CharField(max_length=64)
    token = models.CharField(max_length=64, unique=True, default=new_invite_token)

    #: The submission this invitation opened, if it has been used. A
    #: OneToOne is what enforces one response per invitee.
    submission = models.OneToOneField(
        "responses.Submission",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitation",
    )

    sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # One invitation per person per version. A second send to the
            # same list must not give anyone a second response.
            models.UniqueConstraint(
                fields=["survey_version", "recipient_hash"],
                name="uniq_invitation_per_recipient",
            ),
        ]
        indexes = [models.Index(fields=["batch", "sent_at"])]

    def __str__(self) -> str:
        return f"Invitation {self.id}"
