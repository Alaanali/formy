from django.conf import settings
from django.db import models

from core.models import UUIDModel


class Organization(UUIDModel):
    """A client of the platform. Every survey belongs to exactly one."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Membership(UUIDModel):
    """Organization membership, carrying only org-wide authority."""

    class OrgRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=OrgRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="uniq_membership"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"
