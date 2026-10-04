from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models, transaction

from accounts.models import Organization
from core.models import UUIDModel


class Survey(UUIDModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="surveys")
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="SurveyAccess",
        related_name="accessible_surveys",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_surveys",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="uniq_survey_slug_per_org"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SurveyAccess(UUIDModel):
    """Per-survey grant; the through model of Survey.members."""

    class SurveyRole(models.TextChoices):
        EDITOR = "editor", "Editor"
        ANALYST = "analyst", "Analyst"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="survey_access"
    )
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="access")
    role = models.CharField(max_length=16, choices=SurveyRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "survey"], name="uniq_survey_access"),
        ]
        indexes = [models.Index(fields=["user", "survey"])]

    def __str__(self) -> str:
        return f"{self.user} -> {self.survey} ({self.role})"


class SurveyVersionQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=SurveyVersion.Status.PUBLISHED)

    def create_draft(self, survey: Survey, created_by=None) -> SurveyVersion:
        """Open a new draft for a survey.

        The number is the highest existing plus one, which F() cannot
        express: it references a column of the row being written, not an
        aggregate over siblings. INSERT ... SELECT MAX()+1 would not help
        either, since under READ COMMITTED two transactions read the same
        maximum.

        So the survey row is locked instead. The constraints below would hold
        the line regardless, but the loser would get an opaque conflict error
        for a retryable operation. Draft creation is rare.
        """
        with transaction.atomic():
            # The Survey row, not the versions, so a reader of an existing
            # version is never blocked by someone opening a draft.
            locked = Survey.objects.select_for_update().get(pk=survey.pk)

            latest = self.filter(survey=locked).aggregate(n=models.Max("version_number"))["n"]
            return self.create(
                survey=locked,
                version_number=(latest or 0) + 1,
                status=SurveyVersion.Status.DRAFT,
                created_by=created_by,
            )


class SurveyVersion(UUIDModel):
    """The unit of immutability and caching."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    schema = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = SurveyVersionQuerySet.as_manager()

    class Meta:
        ordering = ["survey", "version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["survey", "version_number"], name="uniq_version_number"
            ),
            # At most one editable draft per survey.
            models.UniqueConstraint(
                fields=["survey"],
                condition=models.Q(status="draft"),
                name="one_draft_per_survey",
            ),
        ]
        indexes = [
            GinIndex(fields=["schema"], name="surveyversion_schema_gin"),
        ]

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    def __str__(self) -> str:
        return f"{self.survey} v{self.version_number} ({self.status})"


class Section(UUIDModel):
    """The authoring representation. The multi-step builder creates and edits
    these one at a time, which is what rows are good at.

    Editable only while the version is a draft. Publish assembles them into
    SurveyVersion.schema and freezes that document; from then on these rows
    are a historical authoring record that nothing on the response path reads.

    One guard keeps the two representations from drifting: a published
    version's sections cannot be written. It lives in save() and delete(),
    which covers every ORM path but not queryset.update() or raw SQL. Full
    enforcement would need a trigger; the frozen schema column is the
    guarantee that matters, since nothing reads these rows after publish.
    """

    version = models.ForeignKey(SurveyVersion, on_delete=models.CASCADE, related_name="sections")
    # Nothing in v1 reads this, deliberately. Deriving a version copies
    # sections into new rows with new primary keys, so the row id does not
    # survive a version bump and this does -- the only handle that lets "the
    # salary section" mean the same thing across v1 and v2.
    key = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    # {field_uuid: definition}; ids are builder-minted, validated at publish.
    content = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "key"]
        constraints = [
            models.UniqueConstraint(fields=["version", "key"], name="uniq_section_key_per_version"),
        ]

    def _assert_version_is_draft(self) -> None:
        if not self.version.is_draft:
            raise ValidationError(
                f"Version {self.version_id} is {self.version.status}; its sections are frozen."
            )

    def clean(self) -> None:
        super().clean()
        self._assert_version_is_draft()

    def save(self, *args, **kwargs):
        # On save, not only full_clean(), so service code is covered too.
        self._assert_version_is_draft()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_version_is_draft()
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.version} / {self.key}"
