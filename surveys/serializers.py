from rest_framework import serializers

from accounts.models import Membership, Organization
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion
from surveys.permissions import effective_role, org_role


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "role", "created_at"]
        read_only_fields = fields

    def get_role(self, obj) -> str | None:
        return org_role(self.context["request"].user, obj.id)


class SurveySerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(read_only=True)
    my_role = serializers.SerializerMethodField()
    published_version = serializers.SerializerMethodField()

    class Meta:
        model = Survey
        fields = [
            "id",
            "organization",
            "name",
            "slug",
            "created_at",
            "archived_at",
            "my_role",
            "published_version",
        ]
        read_only_fields = ["id", "organization", "created_at", "my_role", "published_version"]

    def get_my_role(self, obj) -> str | None:
        return effective_role(self.context["request"].user, obj)

    def get_published_version(self, obj) -> int | None:
        latest = max(
            (v.version_number for v in obj.versions.all() if v.status == "published"),
            default=None,
        )
        return latest

    def validate(self, attrs):
        """Enforce the (organization, slug) uniqueness here."""
        organization = getattr(self.context.get("view"), "organization", None) or getattr(
            self.instance, "organization", None
        )
        slug = attrs.get("slug") or getattr(self.instance, "slug", None)

        if organization and slug:
            clash = Survey.objects.filter(organization=organization, slug=slug)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"slug": "A survey with this slug already exists in this organization."}
                )
        return attrs


class SurveyAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyAccess
        fields = ["id", "user", "survey", "role", "created_at"]
        read_only_fields = ["id", "survey", "created_at"]

    def validate(self, attrs):
        """A grant only means something for a member of the owning org."""
        user = attrs.get("user") or getattr(self.instance, "user", None)
        survey = getattr(self.instance, "survey", None) or self.context.get("survey")

        if user is not None and survey is not None:
            belongs = Membership.objects.filter(
                user=user, organization_id=survey.organization_id
            ).exists()
            if not belongs:
                raise serializers.ValidationError(
                    {"user": "That user is not a member of this survey's organization."}
                )
        return attrs


class SurveyVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyVersion
        fields = [
            "id",
            "survey",
            "version_number",
            "status",
            "created_at",
            "published_at",
        ]
        read_only_fields = fields


class SurveyVersionSchemaSerializer(serializers.ModelSerializer):
    """The assembled document. Separate from the summary serializer so list
    endpoints never carry a full schema per row."""

    class Meta:
        model = SurveyVersion
        fields = ["id", "survey", "version_number", "status", "published_at", "schema"]
        read_only_fields = fields


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ["id", "version", "key", "title", "order", "content"]
        read_only_fields = ["id", "version"]

    def validate_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("content must be an object keyed by field id.")
        return value

    def validate(self, attrs):
        """Same reason as SurveySerializer: (version, key) is enforced by a
        UniqueConstraint, which DRF does not translate into a validator."""
        version = getattr(self.context.get("view"), "parent", None) or getattr(
            self.instance, "version", None
        )
        key = attrs.get("key") or getattr(self.instance, "key", None)

        if version is not None and key:
            clash = Section.objects.filter(version=version, key=key)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"key": "A section with this key already exists in this version."}
                )
        return attrs
