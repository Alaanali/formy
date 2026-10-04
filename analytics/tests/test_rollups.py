import pytest

from analytics.models import FieldAggregate, SurveyStat
from analytics.services import rebuild
from responses.services import save_answers, start_submission

pytestmark = pytest.mark.django_db


def totals(version, field_id):
    return FieldAggregate.objects.get(
        survey_version=version, field_id=field_id, bucket__isnull=True
    )


def bucket(version, field_id, name):
    return FieldAggregate.objects.get(survey_version=version, field_id=field_id, bucket=name)


def complete(version, answers):
    submission = start_submission(version)
    save_answers(submission, answers, complete=True)
    return submission


# --- funnel ------------------------------------------------------------------


def test_starting_a_submission_increments_the_funnel(live_survey):
    start_submission(live_survey)
    start_submission(live_survey)

    stat = SurveyStat.objects.get(survey_version=live_survey)
    assert stat.started_count == 2
    assert stat.completed_count == 0


def test_completing_increments_completions_and_duration(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    stat = SurveyStat.objects.get(survey_version=live_survey)
    assert stat.started_count == 1
    assert stat.completed_count == 1
    assert stat.completion_rate == 1.0
    assert stat.average_duration_seconds is not None


def test_completion_rate_reflects_abandoned_drafts(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    start_submission(live_survey)  # abandoned

    stat = SurveyStat.objects.get(survey_version=live_survey)
    assert stat.completion_rate == 0.5


# --- the denominator ---------------------------------------------------------


def test_eligible_count_excludes_respondents_who_never_saw_the_field(live_survey, ids):
    """The point of tracking eligibility separately. The city field sits in a
    section only Saudi respondents see, so reporting its answers against the
    total submission count would understate them badly."""
    complete(live_survey, {ids["country"]: "sa", ids["age"]: 30, ids["city"]: "riyadh"})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    city = totals(live_survey, ids["city"])
    country = totals(live_survey, ids["country"])

    assert country.eligible_count == 3  # everyone is asked their country
    assert city.eligible_count == 1  # only the Saudi respondent saw the city
    assert city.answered_count == 1
    assert city.share == 1.0  # 100% of those asked, not 33% of everyone


def test_skipped_optional_field_is_eligible_but_unanswered(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg"})  # age left blank

    age = totals(live_survey, ids["age"])
    assert age.eligible_count == 1
    assert age.answered_count == 0
    assert age.share == 0.0


# --- distributions -----------------------------------------------------------


def test_choice_answers_accumulate_per_option(live_survey, ids):
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})
    complete(live_survey, {ids["country"]: "sa", ids["age"]: 18})

    assert bucket(live_survey, ids["country"], "eg").answered_count == 2
    assert bucket(live_survey, ids["country"], "sa").answered_count == 1


def test_numeric_answers_accumulate_sum_min_and_max(live_survey, ids):
    for age in (20, 40, 60):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: age})

    age = totals(live_survey, ids["age"])
    assert age.sum_numeric == 120
    assert age.min_numeric == 20
    assert age.max_numeric == 60
    assert age.answered_count == 3


def test_numeric_answers_fall_into_fixed_buckets(live_survey, ids):
    """Fixed buckets rather than exact percentiles, because these can be
    maintained incrementally and a true p90 cannot."""
    for age in (5, 7, 30):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: age})

    buckets = {
        a.bucket: a.answered_count
        for a in FieldAggregate.objects.filter(
            survey_version=live_survey, field_id=ids["age"], bucket__isnull=False
        )
    }
    assert sum(buckets.values()) == 3
    assert len(buckets) == 2  # 5 and 7 share a bucket, 30 is elsewhere


def test_sensitive_fields_are_counted_but_never_distributed(live_survey, ids):
    """An encrypted answer contributes eligibility and an answered count and
    nothing else -- there is no bucket to put it in."""
    complete(
        live_survey,
        {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1234567890"},
    )

    nid = totals(live_survey, ids["national_id"])
    assert nid.answered_count == 1
    assert not FieldAggregate.objects.filter(
        survey_version=live_survey, field_id=ids["national_id"], bucket__isnull=False
    ).exists()


def test_hidden_answers_never_reach_the_rollups(live_survey, ids):
    """Answer Saudi Arabia, pick Riyadh, change to Egypt. The stale city
    answer must not appear in anyone's results."""
    submission = start_submission(live_survey)
    save_answers(submission, {ids["country"]: "sa", ids["age"]: 30})
    save_answers(submission, {ids["city"]: "riyadh"})
    save_answers(submission, {ids["country"]: "eg"}, complete=True)

    assert not FieldAggregate.objects.filter(
        survey_version=live_survey, field_id=ids["city"]
    ).exists()


# --- atomicity ---------------------------------------------------------------


def test_counters_increment_rather_than_overwrite(live_survey, ids):
    """Assignment would be a read-modify-write and would lose concurrent
    submissions; the conflict clause does arithmetic in the database."""
    for _ in range(5):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    assert bucket(live_survey, ids["country"], "eg").answered_count == 5
    assert totals(live_survey, ids["country"]).eligible_count == 5


def test_the_totals_row_is_updated_not_duplicated(live_survey, ids):
    """Postgres treats NULLs as distinct in a unique index, so without
    nulls_distinct=False every submission would insert a fresh totals row."""
    for _ in range(3):
        complete(live_survey, {ids["country"]: "eg", ids["age"]: 30})

    assert (
        FieldAggregate.objects.filter(
            survey_version=live_survey, field_id=ids["country"], bucket__isnull=True
        ).count()
        == 1
    )


# --- rebuild -----------------------------------------------------------------


def test_rebuild_reproduces_the_same_numbers(live_survey, ids):
    """Only possible because the schema is frozen and hidden answers are
    deleted at completion -- re-running the evaluator over what remains
    reproduces the visibility each respondent saw. No visible_fields column
    is stored, and this is the test that proves it is not needed."""
    complete(live_survey, {ids["country"]: "sa", ids["age"]: 30, ids["city"]: "riyadh"})
    complete(live_survey, {ids["country"]: "eg", ids["age"]: 45})

    before = {
        (a.field_id, a.bucket): (a.eligible_count, a.answered_count, a.sum_numeric)
        for a in FieldAggregate.objects.filter(survey_version=live_survey)
    }

    rebuild(live_survey)

    after = {
        (a.field_id, a.bucket): (a.eligible_count, a.answered_count, a.sum_numeric)
        for a in FieldAggregate.objects.filter(survey_version=live_survey)
    }

    assert after == before
