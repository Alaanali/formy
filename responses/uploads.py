from __future__ import annotations

from django.conf import settings
from django.core.files.storage import default_storage

from responses.models import Submission, SubmissionFile


#: Read lazily rather than captured at import, so override_settings works.
def max_upload_bytes() -> int:
    return settings.MAX_UPLOAD_BYTES


#: Allowlist, not denylist: the set a survey legitimately collects is small.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/csv",
        "text/plain",
    }
)


class UploadRejected(Exception):
    """The upload cannot be accepted. The message is shown to the client."""


def _accepted_field(submission: Submission, field_id):
    """The file field this upload answers, or a refusal."""
    from responses.services import as_uuid, load_answers
    from surveys.cache import get_document
    from surveys.document import FieldType

    document = get_document(submission.survey_version)
    canonical = as_uuid(field_id)
    field = document.fields.get(canonical) if canonical else None

    if field is None:
        raise UploadRejected("Unknown field.")
    if field.type != FieldType.FILE:
        raise UploadRejected("That field does not accept a file.")

    visible = document.visibility(load_answers(submission))
    if not visible.get(canonical, False):
        raise UploadRejected("That question is not being asked of you.")

    return canonical


def _accepted_body(upload) -> str:
    """The upload's declared content type, or a refusal."""
    limit = max_upload_bytes()
    if upload.size > limit:
        raise UploadRejected(f"File is {upload.size} bytes; the limit is {limit}.")

    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UploadRejected(
            f"{content_type or 'unknown'} files are not accepted. "
            f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}."
        )
    return content_type


def store_upload(submission: Submission, field_id: str, upload) -> SubmissionFile:
    """Validate and store one uploaded file against a submission.

    Phase one of two: the client uploads, gets back an id, and sends that id
    as the answer. Carrying the file in the submit payload instead would mean
    a half-finished survey could not hold one, a retry would resend the
    bytes, and a large upload would occupy a worker for the whole transfer.
    The file therefore exists before the answer row, which is why
    SubmissionFile points at the Submission. The production upgrade is a presigned
    PUT this would become.
    """
    canonical = _accepted_field(submission, field_id)
    content_type = _accepted_body(upload)

    record = SubmissionFile(
        submission=submission,
        field_id=canonical,
        # Django's UploadedFile already basenames and truncates this.
        original_name=upload.name,
        content_type=content_type,
        size_bytes=upload.size,
    )

    # Keyed by the record's own id, so a filename can never traverse out of
    # the directory or collide with another respondent's upload. The key the
    # backend actually used is recorded, not the one requested: a backend
    # that suffixes collisions would otherwise leave the row pointing at
    # something never written.
    record.storage_key = default_storage.save(f"uploads/{submission.id}/{record.id}", upload)
    record.save()
    return record


def resolve(submission: Submission, field_id, value) -> SubmissionFile | None:
    """The file an answer refers to, if it is one this submission owns."""
    from responses.services import as_uuid

    pk = as_uuid(value)
    if pk is None:
        return None
    return SubmissionFile.objects.filter(submission=submission, field_id=field_id, pk=pk).first()
