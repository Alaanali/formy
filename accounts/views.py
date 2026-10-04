from functools import cached_property

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import Membership, Organization
from accounts.serializers import (
    MembershipSerializer,
    TokenRequestSerializer,
    TokenSerializer,
    is_last_owner,
)
from core.api import CapabilityScopedMixin
from surveys.permissions import Perm


class ObtainTokenView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    # Unauthenticated and credential-guessing by nature, so it is rate
    # limited harder than anything else.
    throttle_scope = "auth"

    @extend_schema(
        tags=["auth"],
        request=TokenRequestSerializer,
        responses={200: TokenSerializer, 400: OpenApiResponse(description="Invalid credentials.")},
        summary="Exchange credentials for an API token",
        description="Send the token as `Authorization: Token <value>` on later requests.",
    )
    def post(self, request):
        serializer = TokenRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user_id": str(user.pk), "username": user.get_username()}
        )


class RevokeTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        request=None,
        responses={204: OpenApiResponse(description="Token revoked.")},
        summary="Revoke the caller's token",
        description=(
            "Takes effect immediately. Being able to revoke without waiting "
            "for an expiry is the main reason this is a token rather than a "
            "self-contained JWT."
        ),
    )
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WhoAmIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        responses={200: TokenSerializer},
        summary="Identify the authenticated caller",
    )
    def get(self, request):
        return Response({"user_id": str(request.user.pk), "username": request.user.get_username()})


@extend_schema(tags=["organizations"])
class MembershipListCreateView(CapabilityScopedMixin, generics.ListCreateAPIView):
    """Who belongs to this organization, and in what role."""

    serializer_class = MembershipSerializer
    read_perm = Perm.MEMBER_MANAGE
    write_perm = Perm.MEMBER_MANAGE

    @cached_property
    def organization(self):
        return get_object_or_404(
            Organization.objects.filter(memberships__user=self.request.user),
            pk=self.kwargs["organization_id"],
        )

    def permission_object(self):
        return self.organization

    def get_queryset(self):
        return self.organization.memberships.select_related("user").order_by("created_at")

    def perform_create(self, serializer):
        serializer.save(organization=self.organization)


@extend_schema(tags=["organizations"])
class MembershipDetailView(CapabilityScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """Change or revoke one membership."""

    serializer_class = MembershipSerializer
    read_perm = Perm.MEMBER_MANAGE
    write_perm = Perm.MEMBER_MANAGE

    def get_queryset(self):
        # Scoped to organizations the caller belongs to, so an id from
        # another tenant is a 404 rather than a 403.
        return Membership.objects.filter(
            organization__memberships__user=self.request.user
        ).select_related("organization", "user")

    def permission_object(self):
        return self.get_object().organization

    def perform_destroy(self, instance):
        # Same guard as demotion: the last owner cannot be removed, or the
        # organization is left with nobody who can grant access.
        if instance.role == Membership.OrgRole.OWNER and is_last_owner(instance):
            raise DRFValidationError(
                {"role": "This is the organization's only owner. Promote another owner first."}
            )
        instance.delete()
