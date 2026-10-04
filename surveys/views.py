from functools import cached_property

from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization
from core.api import CapabilityScopedMixin, HasCapability
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion
from surveys.permissions import Perm, resolve_survey, visible_surveys
from surveys.publish import derive_draft, publish
from surveys.serializers import (
    OrganizationSerializer,
    SectionSerializer,
    SurveyAccessSerializer,
    SurveySerializer,
    SurveyVersionSchemaSerializer,
    SurveyVersionSerializer,
)


def visible_or_404(user, obj):
    """Enforce tenant scoping on anything in the survey tree."""
    survey = resolve_survey(obj)
    if survey is None:
        raise Http404
    if not visible_surveys(user, survey.organization_id).filter(pk=survey.pk).exists():
        raise Http404
    return obj


class ScopedDetailMixin(CapabilityScopedMixin):
    """Fetch, scope, then check the capability -- in that order."""

    lookup_queryset = None

    def get_object(self):
        obj = get_object_or_404(self.lookup_queryset, pk=self.kwargs["pk"])
        visible_or_404(self.request.user, obj)
        self.check_object_permissions(self.request, obj)
        return obj


class ScopedParentMixin(CapabilityScopedMixin):
    """For nested collections: resolve and scope the parent from the URL."""

    parent_model = None
    parent_kwarg = None
    parent_queryset = None

    @cached_property
    def parent(self):
        """The URL's parent object, scoped to the caller."""
        queryset = self.parent_queryset or self.parent_model.objects.all()
        obj = get_object_or_404(queryset, pk=self.kwargs[self.parent_kwarg])
        return visible_or_404(self.request.user, obj)

    def permission_object(self):
        return self.parent


@extend_schema(tags=["organizations"])
class OrganizationListView(generics.ListAPIView):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.filter(memberships__user=self.request.user).order_by("name")


@extend_schema(tags=["surveys"])
class SurveyListCreateView(CapabilityScopedMixin, generics.ListCreateAPIView):
    serializer_class = SurveySerializer
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_CREATE

    @cached_property
    def organization(self):
        return get_object_or_404(
            Organization.objects.filter(memberships__user=self.request.user),
            pk=self.kwargs["organization_id"],
        )

    def permission_object(self):
        # Listing is scoped by the queryset; creating is checked against the
        # organization, since no survey exists yet to check against.
        return None if self.request.method in ("GET", "HEAD", "OPTIONS") else self.organization

    def get_queryset(self):
        return visible_surveys(self.request.user, self.kwargs["organization_id"]).prefetch_related(
            "versions"
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.organization, created_by=self.request.user)


@extend_schema(tags=["surveys"])
class SurveyDetailView(ScopedDetailMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SurveySerializer
    lookup_queryset = Survey.objects.all()
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_EDIT


@extend_schema(tags=["surveys"])
class SurveyBySlugView(SurveyDetailView):
    """The same survey at a readable address: /o/{org}/surveys/{survey}/.

    Both halves are slugs, which is what keeps the URL short without making
    survey slugs globally unique. Global uniqueness would mean one tenant
    taking "nps" stops every other tenant using it, and would turn a create
    attempt into a probe for who else is a customer.

    Scoped to the organization for the same reason the id route is: the
    lookup stays inside visible_surveys(), so another tenant's survey is a
    404 rather than something discoverable by guessing its name.
    """

    def get_object(self):
        survey = get_object_or_404(
            Survey,
            organization__slug=self.kwargs["org_slug"],
            slug=self.kwargs["slug"],
        )
        visible_or_404(self.request.user, survey)
        self.check_object_permissions(self.request, survey)
        return survey


@extend_schema(tags=["surveys"])
class SurveyVersionListCreateView(ScopedParentMixin, generics.ListCreateAPIView):
    serializer_class = SurveyVersionSerializer
    parent_model = Survey
    parent_kwarg = "survey_id"
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_EDIT

    def get_queryset(self):
        return self.parent.versions.all()

    def create(self, request, *args, **kwargs):
        """Open a draft, seeded from the latest published version when there
        is one, so field ids carry across and analytics stay aligned."""
        survey = self.parent
        latest = survey.versions.published().order_by("-version_number").first()

        version = (
            derive_draft(latest, created_by=request.user)
            if latest
            else SurveyVersion.objects.create_draft(survey, created_by=request.user)
        )
        return Response(self.get_serializer(version).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["surveys"])
class SurveyVersionDetailView(ScopedDetailMixin, generics.RetrieveAPIView):
    serializer_class = SurveyVersionSchemaSerializer
    lookup_queryset = SurveyVersion.objects.select_related("survey")
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_EDIT


@extend_schema(tags=["builder"])
class SectionListCreateView(ScopedParentMixin, generics.ListCreateAPIView):
    serializer_class = SectionSerializer
    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_EDIT

    def get_queryset(self):
        return self.parent.sections.all()

    def perform_create(self, serializer):
        # The model guard rejects writes to a published version; the API
        # exception handler turns that ValidationError into a 400.
        serializer.save(version=self.parent)


@extend_schema(tags=["builder"])
class SectionDetailView(ScopedDetailMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SectionSerializer
    lookup_queryset = Section.objects.select_related("version__survey")
    read_perm = Perm.SURVEY_VIEW
    write_perm = Perm.SURVEY_EDIT


class PublishView(ScopedParentMixin, APIView):
    permission_classes = [HasCapability]
    parent_model = SurveyVersion
    parent_queryset = SurveyVersion.objects.select_related("survey")
    parent_kwarg = "version_id"
    read_perm = Perm.SURVEY_PUBLISH
    write_perm = Perm.SURVEY_PUBLISH

    @extend_schema(
        tags=["builder"],
        request=None,
        responses={
            200: SurveyVersionSchemaSerializer,
            400: OpenApiResponse(
                description="Schema validation failed; every problem is listed under `errors`."
            ),
        },
        summary="Publish a draft version",
        description=(
            "Assembles the draft's sections into one document, validates it "
            "(field ids, operator/type legality, dangling references, cycles), "
            "computes the evaluation order and freezes it. A published version "
            "is immutable."
        ),
    )
    def post(self, request, version_id):
        version = publish(self.parent, published_by=request.user)
        return Response(SurveyVersionSchemaSerializer(version).data)


@extend_schema(tags=["access"])
class SurveyAccessListCreateView(ScopedParentMixin, generics.ListCreateAPIView):
    """Who may work on this survey, and in what role."""

    serializer_class = SurveyAccessSerializer
    parent_model = Survey
    parent_kwarg = "survey_id"
    read_perm = Perm.ACCESS_GRANT
    write_perm = Perm.ACCESS_GRANT

    def get_queryset(self):
        return self.parent.access.select_related("user").order_by("created_at")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "survey": self.parent}

    def perform_create(self, serializer):
        serializer.save(survey=self.parent)


@extend_schema(tags=["access"])
class SurveyAccessDetailView(ScopedDetailMixin, generics.RetrieveUpdateDestroyAPIView):
    """Change or revoke one grant."""

    serializer_class = SurveyAccessSerializer
    lookup_queryset = SurveyAccess.objects.select_related("survey", "user")
    read_perm = Perm.ACCESS_GRANT
    write_perm = Perm.ACCESS_GRANT
