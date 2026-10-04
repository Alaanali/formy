from datetime import timedelta

import pytest
from django.utils import timezone

from analytics.models import FieldAggregate
from analytics.tasks import rebuild_version_aggregates
from responses.models import Submission
from responses.services import save_answers, start_submission

pytestmark = pytest.mark.django_db


def age(submission, days):
    Submission.objects.filter(id=submission.id).update(
        last_activity_at=timezone.now() - timedelta(days=days)
    )


def test_rebuild_task_restores_deleted_aggregates(live_survey, ids):
    start = start_submission(live_survey)
    save_answers(start, {ids["country"]: "eg", ids["age"]: 30}, complete=True)
    expected = FieldAggregate.objects.filter(survey_version=live_survey).count()

    FieldAggregate.objects.filter(survey_version=live_survey).delete()
    rebuild_version_aggregates.delay(str(live_survey.id)).get()

    assert FieldAggregate.objects.filter(survey_version=live_survey).count() == expected


def test_tasks_are_routed_to_the_right_queues():
    """One queue is a single point of contention: a 400k-row export would
    otherwise sit in front of every rollup update."""
    from django.conf import settings

    routes = settings.CELERY_TASK_ROUTES
    assert routes["analytics.tasks.*"]["queue"] == "rollups"
    assert routes["exports.tasks.*"]["queue"] == "exports"
