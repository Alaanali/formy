from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import connection, transaction
from django.db.models import F
from django.db.models.functions import Now

from analytics.models import FieldAggregate, SurveyStat
from responses.models import Submission
from surveys.document import FieldDefinition, FieldType, is_answered, parse

NUMERIC_BUCKETS = 10


def bucket_for(field: FieldDefinition, value: Any) -> str | None:
    """The distribution bucket a value falls in, or None for field types
    whose values are not worth distributing (free text, files)."""
    if field.type in (FieldType.DROPDOWN, FieldType.RADIO):
        return str(value)
    if field.type == FieldType.BOOLEAN:
        return "true" if value else "false"
    if field.type == FieldType.DATE:
        return str(value)[:7]  # year-month
    if field.type == FieldType.NUMBER:
        return _numeric_bucket(field, value)
    return None


def _numeric_bucket(field: FieldDefinition, value: Any) -> str | None:
    """Fixed-width buckets, chosen over exact percentiles because they can be
    maintained incrementally; a true p90 cannot. Real quantiles would want a
    t-digest, not a bigger counter table."""
    try:
        number = Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return None

    low, high = field.min, field.max
    if low is None or high is None or Decimal(str(high)) <= Decimal(str(low)):
        decade = (int(number) // 10) * 10
        return f"{decade}-{decade + 9}"

    low, high = Decimal(str(low)), Decimal(str(high))
    width = (high - low) / NUMERIC_BUCKETS
    index = min(int((number - low) / width), NUMERIC_BUCKETS - 1) if width else 0
    start = low + width * index
    return f"{_trim(start)}-{_trim(start + width)}"


def _trim(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")).normalize())


def buckets_for(field: FieldDefinition, value: Any) -> list[str]:
    """Checkbox answers land in several buckets at once, which is why option
    counts can sum to more than the number of respondents."""
    if field.type == FieldType.CHECKBOX and isinstance(value, list):
        return [str(v) for v in value]
    single = bucket_for(field, value)
    return [single] if single is not None else []


# --- funnel ------------------------------------------------------------------


def record_start(submission: Submission) -> None:
    stat, _ = SurveyStat.objects.get_or_create(survey_version=submission.survey_version)
    SurveyStat.objects.filter(pk=stat.pk).update(
        started_count=F("started_count") + 1, updated_at=Now()
    )


_UPSERT = """
INSERT INTO analytics_fieldaggregate (
    id, survey_version_id, field_id, bucket,
    eligible_count, answered_count, sum_numeric, min_numeric, max_numeric, updated_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
-- clock_timestamp(), not now(): now() is the TRANSACTION start time, so two
-- updates in one transaction would stamp identically.
ON CONFLICT (survey_version_id, field_id, bucket) DO UPDATE SET
    eligible_count = analytics_fieldaggregate.eligible_count + EXCLUDED.eligible_count,
    answered_count = analytics_fieldaggregate.answered_count + EXCLUDED.answered_count,
    sum_numeric    = analytics_fieldaggregate.sum_numeric + EXCLUDED.sum_numeric,
    min_numeric    = LEAST(analytics_fieldaggregate.min_numeric, EXCLUDED.min_numeric),
    max_numeric    = GREATEST(analytics_fieldaggregate.max_numeric, EXCLUDED.max_numeric),
    updated_at     = clock_timestamp()
"""


def _apply(rows: list[tuple]) -> None:
    if not rows:
        return
    with connection.cursor() as cursor:
        cursor.executemany(_UPSERT, rows)


@transaction.atomic
def _aggregate_rows(version_id, field_id, field: FieldDefinition, value: Any) -> list[tuple]:
    """The upsert rows one field contributes."""
    answered = is_answered(value)
    numeric = _as_decimal(field, value) if answered else None

    rows = [
        (
            uuid.uuid7(),
            version_id,
            field_id,
            None,
            1,
            1 if answered else 0,
            numeric or Decimal(0),
            numeric,
            numeric,
        )
    ]

    # Encrypted values are unreadable here, so a sensitive answer contributes
    # counts but never a distribution.
    if answered and not field.sensitive:
        rows += [
            (uuid.uuid7(), version_id, field_id, bucket, 0, 1, Decimal(0), None, None)
            for bucket in buckets_for(field, value)
        ]

    return rows


def _bump_survey_stat(submission: Submission) -> None:
    stat, _ = SurveyStat.objects.get_or_create(survey_version=submission.survey_version)
    duration = 0
    if submission.submitted_at and submission.started_at:
        duration = int((submission.submitted_at - submission.started_at).total_seconds())

    SurveyStat.objects.filter(pk=stat.pk).update(
        completed_count=F("completed_count") + 1,
        sum_duration_seconds=F("sum_duration_seconds") + duration,
        # Explicit because .update() bypasses auto_now, and the results cache
        # keys on this column.
        updated_at=Now(),
    )


def record_completion(
    submission: Submission,
    visible: dict,
    answers: dict,
) -> None:
    """Fold one completed response into the rollups."""
    document = parse(submission.survey_version.schema or {})
    version_id = submission.survey_version_id

    _apply(
        [
            row
            for field_id, field in document.fields.items()
            if field.answerable and visible.get(field_id, False)
            for row in _aggregate_rows(version_id, field_id, field, answers.get(field_id))
        ]
    )
    _bump_survey_stat(submission)


def _as_decimal(field: FieldDefinition, value: Any) -> Decimal | None:
    if field.type != FieldType.NUMBER:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return None


# --- rebuild -----------------------------------------------------------------


@transaction.atomic
def rebuild(version) -> int:
    """Recompute every rollup for a version from stored answers."""
    from responses.services import load_answers

    FieldAggregate.objects.filter(survey_version=version).delete()
    SurveyStat.objects.filter(survey_version=version).delete()

    document = parse(version.schema or {})
    completed = version.submissions.filter(status=Submission.Status.COMPLETED)

    for submission in completed.prefetch_related("answers"):
        answers = load_answers(submission, decrypt_sensitive=False)
        visible = document.visibility(answers)
        record_completion(submission, visible, answers)

    started = version.submissions.count()
    abandoned = version.submissions.filter(status=Submission.Status.ABANDONED).count()
    SurveyStat.objects.filter(survey_version=version).update(
        started_count=started, abandoned_count=abandoned
    )
    return completed.count()
