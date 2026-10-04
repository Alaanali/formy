from celery import shared_task

from analytics.services import rebuild
from surveys.models import SurveyVersion


@shared_task
def rebuild_version_aggregates(version_id) -> int:
    """Recompute a version's rollups from stored answers."""
    version = SurveyVersion.objects.get(pk=version_id)
    return rebuild(version)
