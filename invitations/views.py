from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.audit import log_access
from invitations.serializers import (
    CreateBatchSerializer,
    InvitationBatchSerializer,
    RedeemedSerializer,
)
from invitations.services import InvitationError, create_batch, redeem
from invitations.tasks import send_batch
from surveys.models import SurveyVersion
from surveys.permissions import Perm
from surveys.views import ScopedParentMixin


@extend_schema(tags=["invitations"])
class InvitationBatchListCreateView(ScopedParentMixin, generics.ListCreateAPIView):
    """Send a survey to a list of people."""

    serializer_class = InvitationBatchSerializer
    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.RESPONSE_EXPORT
    write_perm = Perm.RESPONSE_EXPORT

    def get_queryset(self):
        return self.parent.invitation_batches.all()

    @extend_schema(
        request=CreateBatchSerializer,
        responses={201: InvitationBatchSerializer},
        summary="Invite a list of people to a survey",
        description=(
            "Addresses are hashed on arrival and never stored. Re-inviting "
            "someone who already holds an invitation for this version is a "
            "no-op, so nobody gets a second response. Sending happens on a "
            "queue; poll this endpoint for progress."
        ),
    )
    def create(self, request, *args, **kwargs):
        version = self.parent
        form = CreateBatchSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        try:
            batch = create_batch(
                version, form.validated_data["recipients"], requested_by=request.user
            )
        except InvitationError as refused:
            raise ValidationError({"recipients": str(refused)}) from refused

        # A send is a disclosure: the platform now holds who was asked.
        log_access(
            request.user,
            "invitation.send",
            version,
            batch_id=str(batch.id),
            recipients=batch.total,
        )
        send_batch.delay(str(batch.id))

        batch.refresh_from_db()
        return Response(InvitationBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class RedeemInvitationView(APIView):
    """Exchange an invitation token for a submission."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "submission_start"

    @extend_schema(
        tags=["public"],
        request=None,
        responses={
            200: RedeemedSerializer,
            400: OpenApiResponse(description="Invalid, expired or already completed."),
        },
        summary="Open the survey behind an invitation link",
        description=(
            "Idempotent: following the link twice returns the same draft "
            "rather than opening a second one, which is what makes "
            "one-response-per-invitee hold."
        ),
    )
    def post(self, request, token):
        try:
            submission = redeem(token)
        except InvitationError as refused:
            raise ValidationError({"detail": str(refused)}) from refused

        return Response(
            RedeemedSerializer(
                {
                    "id": submission.id,
                    "status": submission.status,
                    "resume_token": submission.resume_token,
                    "resume_expires_at": submission.resume_expires_at,
                }
            ).data
        )
