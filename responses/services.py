from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from analytics.services import record_completion, record_start
from core.audit import Action, log_access
from core.crypto import decrypt, encrypt
from responses.models import Answer, Submission, SubmissionFile
from surveys.cache import get_document
from surveys.document import Document, FieldDefinition, FieldType
from surveys.models import SurveyVersion
from surveys.permissions import Perm

#: Stand-in for an encrypted answer in the analytics payload: enough to count
#: it as answered, carrying none of its content.
SENSITIVE_PRESENT = "__present__"


class AnswerValidationError(Exception):
    """Per-field problems, keyed by field id so a client can show them inline."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def as_uuid(value: Any) -> UUID | None:
    """A UUID, or None when the value is not one."""
    try:
        return UUID(str(value))
    except ValueError, AttributeError, TypeError:
        return None


def _by_field_id(incoming: dict) -> tuple[dict[UUID, Any], dict[str, str]]:
    """Client keys parsed to UUIDs, with an error for any that is not one."""
    parsed: dict[UUID, Any] = {}
    errors: dict[str, str] = {}
    for raw, value in incoming.items():
        field_id = as_uuid(raw)
        if field_id is None:
            errors[str(raw)] = "unknown field"
        else:
            parsed[field_id] = value
    return parsed, errors


# --- per-field validation ----------------------------------------------------


def _text_problem(field: FieldDefinition, value: Any, _: _Allowed) -> str | None:
    if not isinstance(value, str):
        return "expected text"
    if field.max_length and len(value) > field.max_length:
        return f"longer than {field.max_length} characters"
    return None


def _number_problem(field: FieldDefinition, value: Any, _: _Allowed) -> str | None:
    # bool subclasses int, so it would otherwise parse as 0 or 1.
    if isinstance(value, bool):
        return "expected a number"
    try:
        number = Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return "expected a number"
    if field.min is not None and number < Decimal(str(field.min)):
        return f"must be at least {field.min}"
    if field.max is not None and number > Decimal(str(field.max)):
        return f"must be at most {field.max}"
    return None


def _date_problem(_field: FieldDefinition, value: Any, _: _Allowed) -> str | None:
    try:
        date.fromisoformat(str(value))
    except ValueError, TypeError:
        return "expected an ISO date (YYYY-MM-DD)"
    return None


def _boolean_problem(_field: FieldDefinition, value: Any, _: _Allowed) -> str | None:
    return None if isinstance(value, bool) else "expected true or false"


def _choice_problem(_field: FieldDefinition, value: Any, allowed: _Allowed) -> str | None:
    # An unknown option and one the respondent's earlier answers filtered out
    # are the same refusal.
    return None if value in allowed.options else "not an available option"


def _checkbox_problem(_field: FieldDefinition, value: Any, allowed: _Allowed) -> str | None:
    if not isinstance(value, list):
        return "expected a list of option values"
    unknown = [v for v in value if v not in allowed.options]
    if unknown:
        return f"not available options: {unknown}"
    return "contains duplicates" if len(set(value)) != len(value) else None


def _file_problem(_field: FieldDefinition, value: Any, allowed: _Allowed) -> str | None:
    if not isinstance(value, str):
        return "expected an uploaded file id"
    return None if as_uuid(value) in allowed.uploads else "no such upload for this submission"


class _Allowed(NamedTuple):
    """What this respondent may choose right now.

    No default: an optional parameter guarding cross-respondent attribution
    is a hole a future caller reopens silently.
    """

    options: frozenset
    uploads: set[UUID]


#: One validator per field type, so adding a type is an entry rather than a
#: branch. A type absent from the table cannot be answered at all.
VALUE_CHECKS: dict[str, Callable[[FieldDefinition, Any, _Allowed], str | None]] = {
    FieldType.TEXT: _text_problem,
    FieldType.TEXTAREA: _text_problem,
    FieldType.NUMBER: _number_problem,
    FieldType.DATE: _date_problem,
    FieldType.BOOLEAN: _boolean_problem,
    FieldType.DROPDOWN: _choice_problem,
    FieldType.RADIO: _choice_problem,
    FieldType.CHECKBOX: _checkbox_problem,
    FieldType.FILE: _file_problem,
}


def _validate_value(field: FieldDefinition, value: Any, allowed: _Allowed) -> str | None:
    """What is wrong with this answer for this field, or None."""
    check = VALUE_CHECKS.get(field.type)
    if check is None:
        # display, and anything a later version adds without a validator.
        return "static content cannot be answered"
    return check(field, value, allowed)


# --- persistence -------------------------------------------------------------


def _build_answer(
    submission: Submission, field_id: UUID, field: FieldDefinition, value: Any
) -> Answer:
    if field.sensitive:
        return Answer(
            submission=submission,
            field_id=field_id,
            value=encrypt(value, submission_id=submission.id, field_id=str(field_id)),
            is_encrypted=True,
        )

    return Answer(submission=submission, field_id=field_id, value=value, is_encrypted=False)


@transaction.atomic
def save_answers(
    submission: Submission,
    incoming: dict,
    *,
    complete: bool = False,
) -> dict[str, Any]:
    """Validate and persist a batch of answers."""
    if submission.status == Submission.Status.COMPLETED:
        raise AnswerValidationError({"__all__": "This submission is already complete."})

    document = get_document(submission.survey_version)
    parsed, errors = _by_field_id(incoming)
    stored = load_answers(submission, decrypt_sensitive=True)
    merged = {**stored, **parsed}
    visible = document.visibility(merged)

    to_write, batch_errors = _validate_batch(submission, document, parsed, merged, visible)
    errors |= batch_errors
    if complete:
        # Fields that already failed keep their own error. They never reached
        # to_write, so the required check would fire for them too -- and
        # "this field is required" would overwrite "must be at most 120" for
        # a field the respondent had just answered.
        errors |= _unanswered_required(document, merged, visible, to_write, stored, skip=errors)
    if errors:
        raise AnswerValidationError(errors)

    _persist(submission, document, to_write)

    if complete:
        _finalise(submission, document, merged, visible)

    submission.save(update_fields=["last_activity_at"])
    return {"visible": visible, "saved": sorted(str(f) for f in to_write)}


def _validate_batch(
    submission: Submission,
    document: Document,
    incoming: dict[UUID, Any],
    merged: dict[UUID, Any],
    visible: dict[UUID, bool],
) -> tuple[dict[UUID, Any], dict[str, str]]:
    """Check each incoming answer against the field it claims to answer."""
    to_write: dict[UUID, Any] = {}
    errors: dict[str, str] = {}

    # Once for the whole batch: five file fields cost one query, not five.
    allowed_uploads = set(
        SubmissionFile.objects.filter(submission=submission).values_list("id", flat=True)
    )

    for field_id, value in incoming.items():
        field = document.fields.get(field_id)
        if field is None:
            errors[str(field_id)] = "unknown field"
            continue
        if not visible.get(field_id, False):
            # Not an error: the client may be a step behind. Not stored either.
            continue

        problem = _validate_value(
            field,
            value,
            _Allowed(
                options=frozenset(
                    option.value for option in field.available_options(document, merged, visible)
                ),
                uploads=allowed_uploads,
            ),
        )
        if problem:
            errors[str(field_id)] = problem
        else:
            to_write[field_id] = value

    return to_write, errors


def _unanswered_required(
    document: Document,
    merged: dict[UUID, Any],
    visible: dict[UUID, bool],
    to_write: dict[UUID, Any],
    stored: dict[UUID, Any],
    skip: dict[str, str],
) -> dict[str, str]:
    """Required fields still owed an answer."""
    required = document.required(merged, visible)
    return {
        str(field_id): "this field is required"
        for field_id, is_required in required.items()
        if is_required
        and field_id not in to_write
        and field_id not in stored
        and str(field_id) not in skip
    }


def _persist(submission: Submission, document: Document, to_write: dict[UUID, Any]) -> None:
    """One statement, whatever the batch size."""
    if not to_write:
        return

    Answer.objects.bulk_create(
        [
            _build_answer(submission, field_id, document.fields[field_id], value)
            for field_id, value in to_write.items()
        ],
        update_conflicts=True,
        unique_fields=["submission", "field_id"],
        update_fields=["value", "is_encrypted", "updated_at"],
    )


def _finalise(
    submission: Submission,
    document: Document,
    merged: dict[UUID, Any],
    visible: dict[UUID, bool],
) -> None:
    """Close the submission and fold it into the rollups."""
    # Answers to hidden fields must not reach analytics, and dropping them
    # keeps the visible set derivable: re-running the evaluator over what
    # remains reproduces the cascade, so no visible_fields column is needed.
    hidden = [field_id for field_id, shown in visible.items() if not shown]
    if hidden:
        submission.answers.filter(field_id__in=hidden).delete()
        # Their uploads go too: personal data nobody asked for.
        _delete_uploads(submission, hidden)

    submission.status = Submission.Status.COMPLETED
    submission.submitted_at = timezone.now()
    # The bearer credential should not outlive the draft it protected.
    submission.resume_token = None
    submission.save(update_fields=["status", "submitted_at", "resume_token"])

    # Inline for now; moving it to a task changes only this call.
    record_completion(submission, visible, _analytics_view(document, merged, visible))


def _delete_uploads(submission: Submission, field_ids: list[UUID]) -> None:
    """Drop uploads behind fields the logic ended up hiding.

    Rows go inside the transaction; bytes only once it commits. Unlinking is
    not transactional, so deleting inline meant a rollback restored the row
    and lost the bytes forever -- silently, since backends swallow a
    missing-key delete.

    Keys are captured in one query: iterating and then calling .delete() on
    the same queryset re-queries, so a row inserted between the two kept its
    bytes with nothing pointing at them.
    """
    from responses.models import SubmissionFile

    doomed = list(
        SubmissionFile.objects.filter(submission=submission, field_id__in=field_ids).values_list(
            "id", "storage_key"
        )
    )
    if not doomed:
        return

    SubmissionFile.objects.filter(pk__in=[pk for pk, _ in doomed]).delete()
    transaction.on_commit(lambda: _unlink([key for _, key in doomed]))


def _unlink(storage_keys: list[str]) -> None:
    from django.core.files.storage import default_storage

    for key in storage_keys:
        default_storage.delete(key)


def _analytics_view(
    document: Document, answers: dict[UUID, Any], visible: dict[UUID, bool]
) -> dict[str, Any]:
    """Answers with sensitive values replaced by a presence marker."""
    return {
        field_id: (
            SENSITIVE_PRESENT
            if (field := document.fields.get(field_id)) is not None and field.sensitive
            else value
        )
        for field_id, value in answers.items()
        if visible.get(field_id, False)
    }


def load_answers(submission: Submission, *, decrypt_sensitive: bool = False) -> dict[UUID, Any]:
    """Raw answers keyed by field id, with no permission check."""
    out: dict[UUID, Any] = {}

    for answer in submission.answers.all():
        if not answer.is_encrypted:
            out[answer.field_id] = answer.value
        elif decrypt_sensitive:
            out[answer.field_id] = decrypt(
                answer.value, submission_id=submission.id, field_id=str(answer.field_id)
            )
        else:
            out[answer.field_id] = None

    return out


def read_answers(submission: Submission, *, user) -> dict[str, Any]:
    """Read a response for a staff user: permission check, decryption and audit in one place."""
    survey = submission.survey_version.survey
    if not user.has_perm(Perm.RESPONSE_VIEW_RAW, survey):
        raise PermissionDenied("You may not read individual responses for this survey.")

    can_see_pii = user.has_perm(Perm.RESPONSE_VIEW_PII, survey)
    out: dict[str, Any] = {}
    revealed: list[str] = []

    for answer in submission.answers.all():
        field_id = str(answer.field_id)
        if not answer.is_encrypted:
            out[field_id] = answer.value
        elif can_see_pii:
            out[field_id] = decrypt(answer.value, submission_id=submission.id, field_id=field_id)
            revealed.append(field_id)
        else:
            # Redacted, not omitted: a viewer sees that an answer exists.
            out[field_id] = {"__redacted__": True}

    if revealed:
        log_access(user, Action.PII_ACCESS, submission, fields=sorted(revealed))
    else:
        log_access(user, Action.SUBMISSION_READ, submission)

    return out


def start_submission(version: SurveyVersion, *, meta: dict | None = None) -> Submission:
    """Open a draft. The resume window bounds the bearer token's life."""
    submission = Submission.objects.create(
        survey_version=version,
        resume_expires_at=timezone.now() + timedelta(days=settings.RESUME_WINDOW_DAYS),
        meta=meta or {},
    )
    record_start(submission)
    return submission
