import secrets

from django.db import models
from django.utils import timezone

from core.models import UUIDModel
from surveys.models import SurveyVersion

RESUME_TOKEN_BYTES = 32


def new_resume_token() -> str:
    return secrets.token_urlsafe(RESUME_TOKEN_BYTES)


class Submission(UUIDModel):
    """One respondent's answers to one version of a survey."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.PROTECT, related_name="submissions"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)

    resume_token = models.CharField(
        max_length=64, unique=True, null=True, blank=True, default=new_resume_token
    )
    resume_expires_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Hashed IP only: a raw address de-anonymises the respondent.
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["survey_version", "status"]),
            models.Index(fields=["survey_version", "submitted_at"]),
            # Drives the sweeper that marks stale drafts abandoned.
            models.Index(fields=["status", "last_activity_at"]),
        ]

    @property
    def survey_id(self):
        return self.survey_version.survey_id

    @property
    def is_resumable(self) -> bool:
        if self.status != self.Status.IN_PROGRESS:
            return False
        if self.resume_expires_at is None:
            return True
        return self.resume_expires_at > timezone.now()

    def __str__(self) -> str:
        return f"Submission {self.id} ({self.status})"


class Answer(UUIDModel):
    """One answered field.

    A row per field, not one blob per submission: encryption is decided per
    field, and autosave is a per-field upsert made idempotent by the unique
    constraint below.

    `value` holds plaintext JSON or a base64 ciphertext. Which one is decided
    by the is_encrypted COLUMN, never by inspecting the data -- a sentinel
    inside the value would let a client forge an envelope and feed
    attacker-chosen bytes into the decrypt path.
    """

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="answers")
    # UUIDField, not CharField: 16 bytes instead of 36, type-validated free.
    field_id = models.UUIDField()

    value = models.JSONField(null=True, blank=True)

    is_encrypted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Makes autosave an idempotent upsert.
            models.UniqueConstraint(
                fields=["submission", "field_id"], name="uniq_answer_per_field"
            ),
        ]

    def __str__(self) -> str:
        return f"Answer {self.field_id} of {self.submission_id}"


class SubmissionFile(UUIDModel):
    """An uploaded file backing a file-type answer."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    field_id = models.UUIDField()

    storage_key = models.CharField(max_length=512)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.BigIntegerField()

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["submission", "field_id"])]

    def __str__(self) -> str:
        return f"{self.original_name} ({self.size_bytes} bytes)"
