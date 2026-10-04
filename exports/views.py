from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import Action, log_access
from exports.models import Export
from exports.serializers import ExportSerializer
from exports.tasks import generate_export
from surveys.models import SurveyVersion
from surveys.permissions import Perm
from surveys.views import ScopedParentMixin


@extend_schema(tags=["exports"])
class ExportListCreateView(ScopedParentMixin, generics.ListCreateAPIView):
    serializer_class = ExportSerializer
    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.RESPONSE_EXPORT
    write_perm = Perm.RESPONSE_EXPORT

    def get_queryset(self):
        return self.parent.exports.all()

    def create(self, request, *args, **kwargs):
        version = self.parent
        # Resolved now, from this requester's capability. The worker trusts
        # the stored flag, so a later role change cannot retroactively alter
        # a file that has already been produced.
        include_pii = request.user.has_perm(Perm.RESPONSE_VIEW_PII, version.survey)

        export = Export.objects.create(
            survey_version=version, requested_by=request.user, include_pii=include_pii
        )
        log_access(
            request.user,
            Action.EXPORT_CREATE,
            version,
            export_id=str(export.id),
            include_pii=include_pii,
        )
        generate_export.delay(str(export.id))

        export.refresh_from_db()
        return Response(self.get_serializer(export).data, status=status.HTTP_201_CREATED)


class ExportDownloadView(ScopedParentMixin, APIView):
    parent_model = Export
    parent_queryset = Export.objects.select_related("survey_version__survey")
    parent_kwarg = "pk"
    read_perm = Perm.RESPONSE_EXPORT
    write_perm = Perm.RESPONSE_EXPORT

    @extend_schema(
        tags=["exports"],
        responses={
            (200, "text/csv"): OpenApiTypes.BINARY,
            409: OpenApiResponse(description="The export is not ready yet."),
        },
        summary="Download a finished export",
        description="Downloading is itself an access event and is audited.",
    )
    def get(self, request, pk):
        export = self.parent
        if export.status != Export.Status.READY or not export.file_path:
            return Response(
                {"detail": f"Export is {export.status}."},
                status=status.HTTP_409_CONFLICT,
            )

        if not default_storage.exists(export.file_path):
            raise Http404

        # Downloading is itself an access event: the file is a copy of every
        # answer the survey collected.
        log_access(
            request.user,
            Action.EXPORT_CREATE,
            export.survey_version,
            export_id=str(export.id),
            downloaded=True,
        )

        return FileResponse(
            default_storage.open(export.file_path),
            as_attachment=True,
            filename=f"survey-{export.survey_version_id}.csv",
            content_type="text/csv",
        )
