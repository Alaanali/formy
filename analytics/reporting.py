from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache
from django.db.models import Max

from analytics.models import FieldAggregate, SurveyStat
from surveys.cache import get_document
from surveys.document import FieldType

#: Bounds memory, not correctness: the key already carries freshness.
RESULTS_CACHE_SECONDS = 300


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def funnel(version) -> dict:
    stat = SurveyStat.objects.filter(survey_version=version).first()
    if stat is None:
        return {
            "started": 0,
            "completed": 0,
            "abandoned": 0,
            "completion_rate": None,
            "average_duration_seconds": None,
        }
    return {
        "started": stat.started_count,
        "completed": stat.completed_count,
        "abandoned": stat.abandoned_count,
        "completion_rate": stat.completion_rate,
        "average_duration_seconds": stat.average_duration_seconds,
    }


def _field_entry(field_id, field, total, buckets: list) -> dict:
    """One field's slice of the results payload."""
    eligible = total.eligible_count if total else 0
    answered = total.answered_count if total else 0

    entry = {
        "field_id": str(field_id),
        "key": field.key,
        "label": field.label,
        "type": field.type,
        # Against respondents who were shown the field, never against all
        # submissions: conditional logic means those differ, and the second
        # number is simply wrong.
        "eligible": eligible,
        "answered": answered,
    }

    if field.sensitive:
        # Stated rather than silently omitted, so a consumer knows the
        # distribution is unavailable by design and not missing by error.
        entry["distribution_available"] = False
        entry["reason"] = "Field is encrypted at rest; values cannot be aggregated."
        return entry

    entry["distribution_available"] = True
    entry["buckets"] = [
        {
            "bucket": row.bucket,
            "count": row.answered_count,
            "share": _ratio(row.answered_count, eligible),
        }
        for row in sorted(buckets, key=lambda r: r.bucket or "")
    ]

    if field.type == FieldType.NUMBER and total and total.answered_count:
        entry["numeric"] = {
            "sum": _number(total.sum_numeric),
            "min": _number(total.min_numeric),
            "max": _number(total.max_numeric),
            "average": round(float(total.sum_numeric) / total.answered_count, 4),
        }

    return entry


def field_results(version) -> list[dict]:
    document = get_document(version)
    rows = list(FieldAggregate.objects.filter(survey_version=version))

    totals = {row.field_id: row for row in rows if row.bucket is None}
    by_field: dict = {}
    for row in rows:
        if row.bucket is not None:
            by_field.setdefault(row.field_id, []).append(row)

    return [
        _field_entry(field_id, field, totals.get(field_id), by_field.get(field_id, []))
        for field_id, field in document.fields.items()
        if field.answerable
    ]


def _freshness(version) -> str:
    """A token that changes whenever any rollup for this version does.

    Both rollup tables stamp updated_at on every write, so the later of the
    two is this version's data clock.
    """
    latest = [
        FieldAggregate.objects.filter(survey_version=version).aggregate(at=Max("updated_at"))["at"],
        SurveyStat.objects.filter(survey_version=version).aggregate(at=Max("updated_at"))["at"],
    ]
    newest = max((stamp for stamp in latest if stamp is not None), default=None)
    return newest.isoformat() if newest else "empty"


def results(version) -> dict:
    """Aggregate results, cached on the data's own clock.

    Keyed by freshness rather than expiry. A plain TTL made the dashboard lag
    by up to its duration, which is not the "real-time analytics" the brief
    asks for -- measured at 60s before this. Two small aggregates decide
    whether the cached payload is still current, so a new submission produces
    a new key instead of a stale entry at the old one, and there is no
    invalidation to forget. Same property that makes the schema cache correct.
    """
    key = f"results:{version.id}:{_freshness(version)}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    payload = {
        "survey_version": str(version.id),
        "version_number": version.version_number,
        "funnel": funnel(version),
        "fields": field_results(version),
    }
    # An expiry bounds memory only. Correctness comes from the key, so it can
    # never serve stale data -- it only forces a recompute.
    cache.set(key, payload, RESULTS_CACHE_SECONDS)
    return payload
