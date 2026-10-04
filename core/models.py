import uuid

from django.db import models


class UUIDModel(models.Model):
    """Base for every model in the project."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)

    class Meta:
        abstract = True
