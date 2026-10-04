from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.reporting import results
from analytics.serializers import ResultsSerializer, SubmissionAnswersSerializer
from core.api import CapabilityScopedMixin
from core.audit import Action, log_access
from responses.models import Submission, SubmissionFile
from responses.serializers import SubmissionSummarySerializer
from responses.services import read_answers
from surveys.models import Survey, SurveyVersion
from surveys.permissions import Perm
from surveys.views import ScopedParentMixin, visible_or_404


class VersionResultsView(ScopedParentMixin, APIView):
    """Aggregate results for one version, straight from the rollups."""

    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.RESPONSE_VIEW
    write_perm = Perm.RESPONSE_VIEW

    @extend_schema(
        tags=["results"],
        responses=ResultsSerializer,
        summary="Aggregate results for a version",
    )
    def get(self, request, version_id):
        return Response(results(self.parent))


class SurveyResultsView(ScopedParentMixin, APIView):
    """Results for the latest published version of a survey."""

    parent_model = Survey
    parent_kwarg = "survey_id"
    read_perm = Perm.RESPONSE_VIEW
    write_perm = Perm.RESPONSE_VIEW

    @extend_schema(
        tags=["results"],
        responses=ResultsSerializer,
        summary="Aggregate results for the latest published version",
    )
    def get(self, request, survey_id):
        version = self.parent.versions.published().order_by("-version_number").first()
        if version is None:
            return Response({"detail": "This survey has no published version."}, status=404)
        return Response(results(version))


@extend_schema(tags=["responses"], summary="List responses for a version")
class SubmissionListView(ScopedParentMixin, generics.ListAPIView):
    """Individual responses. Separate capability from aggregate results: an
    editor or viewer may see the numbers without opening single records."""

    serializer_class = SubmissionSummarySerializer
    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.RESPONSE_VIEW_RAW
    write_perm = Perm.RESPONSE_VIEW_RAW

    def get_queryset(self):
        return self.parent.submissions.order_by("-submitted_at", "-started_at")


class SubmissionFileDownloadView(CapabilityScopedMixin, APIView):
    """Download a file a respondent uploaded.

    Gated on RESPONSE_VIEW_PII, not RESPONSE_VIEW_RAW: an attached file is
    personal data and its *name* alone routinely identifies the respondent,
    so it follows the same rule as a decrypted answer.

    Always an attachment with a neutral type and nosniff: the declared type
    is client-supplied, so honouring it would let an HTML file uploaded as
    image/png execute on this origin.
    """

    read_perm = Perm.RESPONSE_VIEW_PII
    write_perm = Perm.RESPONSE_VIEW_PII

    def permission_object(self):
        record = get_object_or_404(
            SubmissionFile.objects.select_related("submission__survey_version__survey"),
            pk=self.kwargs["pk"],
        )
        return visible_or_404(self.request.user, record.submission)

    @extend_schema(
        tags=["responses"],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
        summary="Download an uploaded file",
        description=(
            "Requires `response.view_pii`: a filename alone often identifies "
            "the respondent. Always an attachment, never served inline."
        ),
    )
    def get(self, request, pk):
        record = get_object_or_404(
            SubmissionFile.objects.select_related("submission__survey_version__survey"),
            pk=pk,
        )
        visible_or_404(request.user, record.submission)
        self.check_object_permissions(request, record.submission)

        if not default_storage.exists(record.storage_key):
            raise Http404

        log_access(
            request.user,
            Action.PII_ACCESS,
            record.submission,
            file_id=str(record.id),
            filename=record.original_name,
        )

        response = FileResponse(
            # Through open_body, so a sealed file is decrypted here rather
            # than handed to the browser as ciphertext.
            default_storage.open(record.storage_key),
            as_attachment=True,
            filename=record.original_name,
            # Deliberately not record.content_type: that value is
            # client-declared and stored verbatim, so trusting it here would
            # turn an uploaded HTML file into stored XSS on this origin.
            content_type="application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


class SubmissionAnswersView(CapabilityScopedMixin, APIView):
    """One response, decrypted according to the caller's capabilities."""

    read_perm = Perm.RESPONSE_VIEW_RAW
    write_perm = Perm.RESPONSE_VIEW_RAW

    def permission_object(self):
        submission = get_object_or_404(
            Submission.objects.select_related("survey_version__survey"),
            pk=self.kwargs["pk"],
        )
        return visible_or_404(self.request.user, submission)

    @extend_schema(
        tags=["responses"],
        responses=SubmissionAnswersSerializer,
        summary="Read one response",
        description=(
            "Requires `response.view_raw`. Sensitive answers are decrypted only "
            "with `response.view_pii`, and every such read writes an audit entry."
        ),
    )
    def get(self, request, pk):
        submission = self.permission_object()
        return Response(
            {
                "submission": SubmissionSummarySerializer(submission).data,
                "answers": read_answers(submission, user=request.user),
            }
        )
