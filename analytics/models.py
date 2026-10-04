from django.db import models

from core.models import UUIDModel
from surveys.models import SurveyVersion


class SurveyStat(UUIDModel):
    """Funnel counters. Incremented, never recomputed."""

    survey_version = models.OneToOneField(
        SurveyVersion, on_delete=models.CASCADE, related_name="stat"
    )
    started_count = models.BigIntegerField(default=0)
    completed_count = models.BigIntegerField(default=0)
    abandoned_count = models.BigIntegerField(default=0)
    sum_duration_seconds = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def completion_rate(self) -> float | None:
        if not self.started_count:
            return None
        return round(self.completed_count / self.started_count, 4)

    @property
    def average_duration_seconds(self) -> int | None:
        if not self.completed_count:
            return None
        return self.sum_duration_seconds // self.completed_count


class FieldAggregate(UUIDModel):
    """Per-field distribution: one row per (version, field, bucket).

    `bucket` is the option value for a choice field, a histogram bucket for a
    numeric one, or NULL for the field's totals row.

    eligible_count is tracked separately from answered_count because
    conditional logic means not every respondent is shown every field.
    Reporting "60 of 1000 chose option A" is wrong when only 100 people were
    ever asked -- the real figure is 60%, not 6%. Percentages are computed
    against eligible.
    """

    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.CASCADE, related_name="aggregates"
    )
    field_id = models.UUIDField()
    bucket = models.CharField(max_length=128, null=True, blank=True)  # noqa: DJ001

    eligible_count = models.BigIntegerField(default=0)
    answered_count = models.BigIntegerField(default=0)

    sum_numeric = models.DecimalField(max_digits=24, decimal_places=4, default=0)
    min_numeric = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    max_numeric = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # NULL buckets must not collide: Postgres treats NULLs as distinct
            # in a unique index, so without this the totals row would be
            # inserted afresh on every submission instead of incremented.
            models.UniqueConstraint(
                fields=["survey_version", "field_id", "bucket"],
                name="uniq_field_aggregate",
                nulls_distinct=False,
            ),
        ]
        indexes = [models.Index(fields=["survey_version", "field_id"])]

    @property
    def share(self) -> float | None:
        """Against eligible respondents, not total submissions."""
        if not self.eligible_count:
            return None
        return round(self.answered_count / self.eligible_count, 4)
