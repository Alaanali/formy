from __future__ import annotations

import csv
import io

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from core.crypto import decrypt
from exports.models import Export
from responses.models import Submission
from responses.services import as_uuid
from surveys.cache import get_document
from surveys.document import Document, FieldType

REDACTED = "[redacted]"
BATCH = 500


def _header(document: Document) -> tuple[list, list[str]]:
    """Column ids and their human labels."""
    ids = document.answerable_ids()
    labels = [document.fields[fid].label or document.fields[fid].key or str(fid) for fid in ids]
    return ids, labels


def _cell(answer, *, is_file: bool, include_pii: bool, files: dict):
    """One CSV cell."""
    value = answer.value

    if answer.is_encrypted:
        if not include_pii:
            return REDACTED
        value = decrypt(
            answer.value, submission_id=answer.submission_id, field_id=str(answer.field_id)
        )

    if is_file:
        # A filename is respondent-supplied text that routinely contains
        # their name, so it follows the same rule as any sensitive value.
        # Without the PII capability the caller gets the inert id.
        name = files.get(as_uuid(value))
        if name is None:
            return value
        return _defuse(name) if include_pii else REDACTED

    return ",".join(str(v) for v in value) if isinstance(value, list) else value


#: Spreadsheets evaluate a cell beginning with any of these.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _defuse(text: str) -> str:
    """Stop a spreadsheet treating respondent text as a formula.

    A filename is chosen by an anonymous respondent and opened in Excel, so
    `=1+1.pdf` would be evaluated. An apostrophe is the conventional escape.
    """
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def _row(submission, document: Document, field_ids: list, include_pii: bool) -> list:
    """One submission as a CSV row, in the header's column order."""
    answers = {answer.field_id: answer for answer in submission.answers.all()}
    files = {f.id: f.original_name for f in submission.files.all()}

    return [
        str(submission.id),
        submission.submitted_at.isoformat() if submission.submitted_at else "",
        *[
            _cell(
                answers[field_id],
                is_file=document.fields[field_id].type == FieldType.FILE,
                include_pii=include_pii,
                files=files,
            )
            if field_id in answers
            else ""
            for field_id in field_ids
        ],
    ]


@shared_task(bind=True, max_retries=2)
def generate_export(self, export_id) -> int:
    export = Export.objects.select_related("survey_version").get(pk=export_id)
    Export.objects.filter(pk=export.pk).update(status=Export.Status.RUNNING)

    try:
        document = get_document(export.survey_version)
        field_ids, labels = _header(document)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["submission_id", "submitted_at", *labels])

        rows = 0
        queryset = (
            Submission.objects.filter(
                survey_version=export.survey_version, status=Submission.Status.COMPLETED
            )
            .prefetch_related("answers", "files")
            .order_by("submitted_at")
        )

        # iterator() with a chunk size keeps a large export from loading
        # every submission into memory at once.
        for submission in queryset.iterator(chunk_size=BATCH):
            writer.writerow(_row(submission, document, field_ids, export.include_pii))
            rows += 1

        path = f"exports/{export.survey_version_id}/{export.id}.csv"
        default_storage.save(path, ContentFile(buffer.getvalue().encode()))

        Export.objects.filter(pk=export.pk).update(
            status=Export.Status.READY,
            file_path=path,
            row_count=rows,
            completed_at=timezone.now(),
        )
        return rows

    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for retry
        Export.objects.filter(pk=export.pk).update(
            status=Export.Status.FAILED, error=str(exc)[:1000], completed_at=timezone.now()
        )
        raise
