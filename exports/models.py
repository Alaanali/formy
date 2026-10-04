from django.conf import settings
from django.db import models

from core.models import UUIDModel
from surveys.models import SurveyVersion


class Export(UUIDModel):
    """A requested data extract."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.CASCADE, related_name="exports"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="exports"
    )

    # Decided when the export is requested, from the requester's capability
    # at that moment. The worker trusts this flag rather than re-deriving it,
    # so a later role change cannot retroactively alter a finished file.
    include_pii = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    file_path = models.CharField(max_length=512, blank=True, default="")
    row_count = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["survey_version", "-created_at"])]

    def __str__(self) -> str:
        return f"Export {self.id} ({self.status})"
