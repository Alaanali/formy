from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from responses.models import Submission
from responses.permissions import HasValidResumeToken
from responses.serializers import (
    AnswerBatchSerializer,
    StartSubmissionSerializer,
    SubmissionFileSerializer,
    SubmissionStateSerializer,
    UploadSerializer,
)
from responses.services import load_answers, save_answers, start_submission
from responses.uploads import UploadRejected, store_upload
from surveys.cache import get_document
from surveys.models import SurveyVersion

RESUME_PARAM = OpenApiParameter(
    name="X-Resume-Token",
    location=OpenApiParameter.HEADER,
    required=True,
    type=str,
    description=(
        "The token returned when the submission was started. Sent as a header "
        "rather than in the URL, because a credential in a path ends up in "
        "access logs, proxy logs and Referer headers."
    ),
)


def submission_state(submission: Submission) -> dict:
    """Everything the client needs to render the next step, computed by the
    server: resolved visibility, requiredness and filtered option lists.

    The client may re-derive this for responsiveness, but the server
    recomputes all of it on write: this payload is a convenience, never the
    authority.
    """
    document = get_document(submission.survey_version)
    answers = load_answers(submission)
    visible = document.visibility(answers)
    required = document.required(answers, visible)

    options = {
        field_id: [option.value for option in field.available_options(document, answers, visible)]
        for field_id, field in document.fields.items()
        if field.options
    }

    return {
        "id": submission.id,
        # Shown at the top of the form: a respondent arrives from a link and
        # should be able to tell what they are answering.
        "survey": submission.survey_version.survey.name,
        "status": submission.status,
        "started_at": submission.started_at,
        "last_activity_at": submission.last_activity_at,
        "submitted_at": submission.submitted_at,
        "resume_expires_at": submission.resume_expires_at,
        # UUID keys inside, string keys on the wire: stringified here and
        # nowhere else.
        "schema": document.to_stored(),
        "answers": _by_id(answers),
        "visible": _by_id(visible),
        "required": _by_id(required),
        "options": _by_id(options),
    }


def _by_id(mapping: dict) -> dict[str, object]:
    return {str(field_id): value for field_id, value in mapping.items()}


class StartSubmissionView(APIView):
    """Open a draft against a published version. Anonymous by design."""

    # No DRF authenticator: respondents are anonymous and authenticate with
    # the X-Resume-Token header through the permission class. Leaving the
    # project default in place would make DRF answer an unauthenticated
    # request with 401 and WWW-Authenticate: Token, advertising a staff
    # scheme that does not work here.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "submission_start"

    @extend_schema(
        tags=["public"],
        request=None,
        responses={201: StartSubmissionSerializer},
        summary="Start a submission",
        description=(
            "Anonymous. Returns a resume token, which is the only credential "
            "protecting the draft and is never returned again -- store it."
        ),
    )
    def post(self, request, version_id):
        version = get_object_or_404(
            SurveyVersion.objects.filter(status=SurveyVersion.Status.PUBLISHED),
            pk=version_id,
        )
        submission = start_submission(version, meta=request_meta(request))
        return Response(StartSubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)


def request_meta(request) -> dict:
    """Hashed IP only. Storing the raw address would de-anonymise a
    respondent we deliberately created no account for."""
    import hashlib

    from django.conf import settings

    raw = request.META.get("REMOTE_ADDR", "")
    salted = f"{settings.SECRET_KEY}:{raw}".encode()
    return {
        "ip_hash": hashlib.sha256(salted).hexdigest()[:32] if raw else None,
        "user_agent": request.headers.get("User-Agent", "")[:512],
    }


class SubmissionView(APIView):
    """Read current state, or autosave a batch of answers."""

    # No DRF authenticator: respondents are anonymous and authenticate with
    # the X-Resume-Token header through the permission class. Leaving the
    # project default in place would make DRF answer an unauthenticated
    # request with 401 and WWW-Authenticate: Token, advertising a staff
    # scheme that does not work here.
    authentication_classes = []
    permission_classes = [HasValidResumeToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "submission_write"

    def get_submission(self, pk) -> Submission:
        submission = get_object_or_404(
            Submission.objects.select_related("survey_version__survey"), pk=pk
        )
        self.check_object_permissions(self.request, submission)
        return submission

    @extend_schema(
        tags=["public"],
        parameters=[RESUME_PARAM],
        responses=SubmissionStateSerializer,
        summary="Read current state",
        description=(
            "Returns server-resolved visibility, requiredness and filtered "
            "option lists, so a client renders exactly what the server will "
            "accept. Sensitive answers come back as null."
        ),
    )
    def get(self, request, pk):
        submission = self.get_submission(pk)
        return Response(SubmissionStateSerializer(submission_state(submission)).data)

    @extend_schema(
        tags=["public"],
        parameters=[RESUME_PARAM],
        request=AnswerBatchSerializer,
        responses={
            200: SubmissionStateSerializer,
            400: OpenApiResponse(description="Per-field validation errors, keyed by field id."),
        },
        summary="Autosave a batch of answers",
        description=(
            "Partial by design. Required fields are not enforced here, so a "
            "half-filled form always saves. Answers to fields the logic hides "
            "are silently not stored."
        ),
    )
    def patch(self, request, pk):
        submission = self.get_submission(pk)
        batch = AnswerBatchSerializer(data=request.data)
        batch.is_valid(raise_exception=True)

        save_answers(submission, batch.validated_data["answers"])
        submission.refresh_from_db()
        return Response(SubmissionStateSerializer(submission_state(submission)).data)


class UploadView(APIView):
    """Phase one of a file answer: store the bytes, return an id."""

    authentication_classes = []
    permission_classes = [HasValidResumeToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "submission_write"
    # Multipart, not JSON: base64 inside a JSON body inflates the payload by
    # a third and has to be buffered twice.
    parser_classes = [MultiPartParser]

    @extend_schema(
        tags=["public"],
        parameters=[RESUME_PARAM],
        request={"multipart/form-data": UploadSerializer},
        responses={
            201: SubmissionFileSerializer,
            400: OpenApiResponse(
                description="Rejected: wrong field, unsupported type, or too large."
            ),
        },
        summary="Upload a file for a file-type question",
    )
    def post(self, request, pk):
        submission = get_object_or_404(
            Submission.objects.select_related("survey_version__survey"), pk=pk
        )
        self.check_object_permissions(request, submission)

        form = UploadSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        try:
            record = store_upload(
                submission,
                str(form.validated_data["field_id"]),
                form.validated_data["file"],
            )
        except UploadRejected as rejected:
            raise ValidationError({"file": str(rejected)}) from rejected

        return Response(SubmissionFileSerializer(record).data, status=status.HTTP_201_CREATED)


class SubmitView(APIView):
    """Finalise. Required fields are enforced here and nowhere earlier, so
    autosave never rejects a half-filled form."""

    # No DRF authenticator: respondents are anonymous and authenticate with
    # the X-Resume-Token header through the permission class. Leaving the
    # project default in place would make DRF answer an unauthenticated
    # request with 401 and WWW-Authenticate: Token, advertising a staff
    # scheme that does not work here.
    authentication_classes = []
    permission_classes = [HasValidResumeToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "submission_write"

    @extend_schema(
        tags=["public"],
        parameters=[RESUME_PARAM],
        request=AnswerBatchSerializer,
        responses={
            200: OpenApiResponse(description="Submission completed."),
            400: OpenApiResponse(description="Required fields missing, or invalid answers."),
        },
        summary="Finalise a submission",
        description=(
            "Enforces required fields, deletes answers to fields the logic "
            "ended up hiding, folds the response into the rollups and "
            "invalidates the resume token."
        ),
    )
    def post(self, request, pk):
        submission = get_object_or_404(
            Submission.objects.select_related("survey_version__survey"), pk=pk
        )
        self.check_object_permissions(request, submission)

        batch = AnswerBatchSerializer(data=request.data or {"answers": {}})
        batch.is_valid(raise_exception=True)

        save_answers(submission, batch.validated_data["answers"], complete=True)
        submission.refresh_from_db()
        return Response(
            {
                "id": submission.id,
                "status": submission.status,
                "submitted_at": submission.submitted_at,
            }
        )
