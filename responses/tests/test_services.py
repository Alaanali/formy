import pytest

from responses.models import Answer, Submission
from responses.services import (
    AnswerValidationError,
    load_answers,
    save_answers,
    start_submission,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def submission(live_survey):
    return start_submission(live_survey)


# --- happy path --------------------------------------------------------------


def test_partial_save_stores_only_what_was_sent(submission, ids, uid):
    save_answers(submission, {ids["country"]: "sa"})

    assert load_answers(submission) == {uid["country"]: "sa"}
    assert submission.status == Submission.Status.IN_PROGRESS


def test_autosave_is_idempotent(submission, ids, uid):
    save_answers(submission, {ids["country"]: "sa"})
    save_answers(submission, {ids["country"]: "sa"})
    save_answers(submission, {ids["country"]: "eg"})

    assert submission.answers.count() == 1
    assert load_answers(submission)[uid["country"]] == "eg"


def test_completing_a_submission(submission, ids):
    save_answers(submission, {ids["country"]: "sa", ids["age"]: 30})
    save_answers(submission, {ids["city"]: "riyadh"}, complete=True)

    submission.refresh_from_db()
    assert submission.status == Submission.Status.COMPLETED
    assert submission.submitted_at is not None


def test_completing_clears_the_resume_token(submission, ids):
    """The bearer credential should not outlive the draft it protected."""
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)

    submission.refresh_from_db()
    assert submission.resume_token is None
    assert submission.is_resumable is False


def test_a_completed_submission_cannot_be_edited(submission, ids):
    save_answers(submission, {ids["country"]: "eg"}, complete=True)

    with pytest.raises(AnswerValidationError, match="already complete"):
        save_answers(submission, {ids["country"]: "sa"})


# --- the server re-derives visibility ----------------------------------------


def test_answers_to_hidden_fields_are_not_stored(submission, ids, uid):
    """The location section is gated on country == sa. A client that posts a
    city anyway must not have it stored."""
    save_answers(submission, {ids["country"]: "eg", ids["city"]: "cairo"})

    assert uid["city"] not in load_answers(submission)


def test_cross_section_dependency_is_enforced_server_side(submission, ids, uid):
    save_answers(submission, {ids["country"]: "sa"})
    save_answers(submission, {ids["city"]: "riyadh"})

    assert load_answers(submission)[uid["city"]] == "riyadh"


def test_option_filtering_is_enforced_server_side(submission, ids):
    """Cairo is only offered when the country is Egypt, and Egypt hides the
    whole section -- so the server refuses it either way."""
    save_answers(submission, {ids["country"]: "sa"})

    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["city"]: "cairo"})

    assert "not an available option" in exc.value.errors[ids["city"]]


def test_visibility_is_resolved_over_stored_plus_incoming(submission, ids, uid):
    """A field in section 2 depends on an answer given in an earlier request,
    so the merged picture is what counts -- not the current batch alone."""
    save_answers(submission, {ids["country"]: "sa"})
    result = save_answers(submission, {ids["comments"]: "all good"})

    assert result["visible"][uid["city"]] is True
    assert load_answers(submission)[uid["comments"]] == "all good"


def test_hidden_answers_are_deleted_on_completion(submission, ids, uid):
    """Answer Saudi Arabia, pick Riyadh, then change country. The stale city
    answer must not reach analytics -- and dropping it is what keeps the
    visible set derivable from stored answers afterwards."""
    save_answers(submission, {ids["country"]: "sa", ids["age"]: 30})
    save_answers(submission, {ids["city"]: "riyadh"})
    assert uid["city"] in load_answers(submission)

    save_answers(submission, {ids["country"]: "eg"}, complete=True)

    assert uid["city"] not in load_answers(submission)


# --- validation --------------------------------------------------------------


def test_unknown_field_is_rejected(submission):
    import uuid

    with pytest.raises(AnswerValidationError, match="unknown field"):
        save_answers(submission, {str(uuid.uuid7()): "x"})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("abc", "expected a number"),
        (True, "expected a number"),
        (-1, "must be at least 0"),
        (200, "must be at most 120"),
    ],
)
def test_number_validation(submission, ids, value, message):
    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["age"]: value})

    assert message in exc.value.errors[ids["age"]]


def test_text_length_is_enforced(submission, ids):
    save_answers(submission, {ids["country"]: "sa"})

    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["comments"]: "x" * 51})

    assert "longer than 50" in exc.value.errors[ids["comments"]]


def test_unknown_choice_is_rejected(submission, ids):
    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["country"]: "fr"})

    assert "not an available option" in exc.value.errors[ids["country"]]


def test_all_field_errors_are_reported_together(submission, ids):
    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["country"]: "fr", ids["age"]: "abc"})

    assert set(exc.value.errors) == {ids["country"], ids["age"]}


def test_required_fields_are_only_enforced_at_completion(submission, ids):
    save_answers(submission, {ids["age"]: 30})  # country is required, not sent

    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["age"]: 31}, complete=True)

    assert "required" in exc.value.errors[ids["country"]]


def test_conditionally_required_field_is_enforced_when_its_rule_holds(submission, ids):
    save_answers(submission, {ids["country"]: "sa", ids["age"]: 25})

    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {}, complete=True)

    assert "required" in exc.value.errors[ids["city"]]


def test_conditionally_required_field_is_not_enforced_when_its_rule_fails(submission, ids):
    save_answers(submission, {ids["country"]: "sa", ids["age"]: 18}, complete=True)

    submission.refresh_from_db()
    assert submission.status == Submission.Status.COMPLETED


def test_hidden_required_field_never_blocks_completion(submission, ids):
    """City is required for over-21s, but Egypt hides its whole section. A
    hidden required field must not make the survey impossible to finish."""
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 40}, complete=True)

    submission.refresh_from_db()
    assert submission.status == Submission.Status.COMPLETED


def test_a_failed_save_writes_nothing(submission, ids):
    with pytest.raises(AnswerValidationError):
        save_answers(submission, {ids["country"]: "sa", ids["age"]: "abc"})

    assert submission.answers.count() == 0


# --- encryption --------------------------------------------------------------


def test_sensitive_answers_are_encrypted_at_rest(submission, ids):
    save_answers(submission, {ids["national_id"]: "1234567890"})

    row = Answer.objects.get(submission=submission, field_id=ids["national_id"])
    assert row.is_encrypted is True
    assert "1234567890" not in row.value


def test_sensitive_answers_round_trip(submission, ids, uid):
    save_answers(submission, {ids["national_id"]: "1234567890"})

    assert load_answers(submission, decrypt_sensitive=True)[uid["national_id"]] == "1234567890"


def test_sensitive_answers_are_masked_without_decryption(submission, ids, uid):
    save_answers(submission, {ids["national_id"]: "1234567890"})

    assert load_answers(submission)[uid["national_id"]] is None


def test_non_sensitive_answers_are_stored_in_the_clear(submission, ids):
    save_answers(submission, {ids["country"]: "sa"})

    row = Answer.objects.get(submission=submission, field_id=ids["country"])
    assert row.is_encrypted is False
    assert row.value == "sa"


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("country", "zz", "not an available option"),
        ("age", 999, "must be at most 120"),
        ("age", -1, "must be at least 0"),
        ("age", "abc", "expected a number"),
        ("age", True, "expected a number"),
        ("comments", "x" * 80, "longer than 50 characters"),
        ("comments", 12, "expected text"),
        ("national_id", 5, "expected text"),
    ],
)
def test_a_bad_answer_reports_why_not_that_it_is_missing(submission, ids, key, value, expected):
    """At submit, every field that failed validation keeps its own message.

    The required sweep also fires for them -- a value that failed never
    reaches to_write -- and a dict union let "this field is required"
    overwrite the specific reason for a field the respondent had answered.
    """
    # country=sa keeps every field in the survey visible, so the field under
    # test is actually reached rather than silently dropped as hidden.
    answers = {ids["country"]: "sa"}
    if key != "age":
        answers[ids["age"]] = 18
    answers[ids[key]] = value

    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, answers, complete=True)

    assert expected in exc.value.errors[ids[key]]


def test_an_invalid_answer_keeps_its_own_error_at_submit(submission, ids):
    """A required field answered badly must report *why* it is bad.

    _unanswered_required also fires for it -- the value failed validation so
    it never reached to_write -- and a dict union let the generic message
    overwrite the specific one. The respondent saw "this field is required"
    for a field they had just answered.
    """
    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["country"]: "zz"}, complete=True)

    assert exc.value.errors[ids["country"]] == "not an available option"


def test_a_number_outside_its_range_says_so(submission, live_survey, ids):
    """The reported case: max=120, answered 999."""
    with pytest.raises(AnswerValidationError) as exc:
        save_answers(submission, {ids["country"]: "eg", ids["age"]: 999}, complete=True)

    assert "must be at most 120" in exc.value.errors[ids["age"]]
