import pytest
from auditlog.models import LogEntry
from django.core.exceptions import PermissionDenied

from accounts.models import Membership
from core.audit import Action
from responses.services import read_answers, save_answers, start_submission
from surveys.models import Survey, SurveyAccess

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole
pytestmark = pytest.mark.django_db


def access_entries(event=None):
    entries = LogEntry.objects.filter(action=LogEntry.Action.ACCESS)
    if event:
        entries = [e for e in entries if (e.additional_data or {}).get("event") == event]
    return list(entries)


@pytest.fixture
def answered(live_survey, ids):
    submission = start_submission(live_survey)
    save_answers(
        submission,
        {ids["country"]: "eg", ids["age"]: 30, ids["national_id"]: "1234567890"},
        complete=True,
    )
    return submission


# --- mutations, captured by signals ------------------------------------------


def test_creating_a_survey_is_logged(org):
    survey = Survey.objects.create(organization=org, name="NPS", slug="nps")

    entries = LogEntry.objects.get_for_object(survey)
    assert entries.filter(action=LogEntry.Action.CREATE).exists()


def test_editing_a_survey_records_the_diff(survey):
    survey.name = "Renamed"
    survey.save()

    entry = LogEntry.objects.get_for_object(survey).filter(action=LogEntry.Action.UPDATE).first()
    assert "name" in entry.changes_dict


def test_granting_access_is_logged(survey, user_factory):
    """SurveyAccess carries no granted_by column, so this log is the only
    record of who granted whom access -- registration is required, not a
    nicety."""
    access = SurveyAccess.objects.create(user=user_factory(), survey=survey, role=SurveyRole.VIEWER)

    assert LogEntry.objects.get_for_object(access).filter(action=LogEntry.Action.CREATE).exists()


def test_responses_are_not_registered(answered):
    """One log row per answer would make the audit table larger than the data
    it describes. Responses are data, not configuration."""
    assert (
        not LogEntry.objects.get_for_object(answered)
        .filter(action__in=[LogEntry.Action.CREATE, LogEntry.Action.UPDATE])
        .exists()
    )

    answer = answered.answers.first()
    assert not LogEntry.objects.get_for_object(answer).exists()


def test_the_schema_blob_is_excluded_from_diffs(draft):
    """A JSON diff of a whole survey document is noise."""
    draft.schema = {"fields": {}}
    draft.save()

    entries = LogEntry.objects.get_for_object(draft).filter(action=LogEntry.Action.UPDATE)
    assert all("schema" not in (e.changes_dict or {}) for e in entries)


# --- access, which signals cannot see ----------------------------------------


def test_analyst_reading_pii_writes_an_access_entry(answered, member_factory, grant, ids):
    analyst = member_factory(answered.survey_version.survey.organization, OrgRole.MEMBER)
    grant(analyst, answered.survey_version.survey, SurveyRole.ANALYST)

    values = read_answers(answered, user=analyst)

    assert values[ids["national_id"]] == "1234567890"
    entries = access_entries(Action.PII_ACCESS)
    assert len(entries) == 1
    assert entries[0].additional_data["fields"] == [ids["national_id"]]
    assert entries[0].actor == analyst


def test_viewer_cannot_read_an_individual_response(answered, member_factory, grant):
    viewer = member_factory(answered.survey_version.survey.organization, OrgRole.MEMBER)
    grant(viewer, answered.survey_version.survey, SurveyRole.VIEWER)

    with pytest.raises(PermissionDenied):
        read_answers(answered, user=viewer)


def test_editor_cannot_read_an_individual_response(answered, member_factory, grant):
    """Building a survey does not imply the right to read the personal data
    it collects."""
    editor = member_factory(answered.survey_version.survey.organization, OrgRole.MEMBER)
    grant(editor, answered.survey_version.survey, SurveyRole.EDITOR)

    with pytest.raises(PermissionDenied):
        read_answers(answered, user=editor)


def test_a_read_without_pii_logs_a_plain_access_entry(live_survey, member_factory, grant, ids):
    submission = start_submission(live_survey)
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)

    analyst = member_factory(live_survey.survey.organization, OrgRole.MEMBER)
    grant(analyst, live_survey.survey, SurveyRole.ANALYST)
    read_answers(submission, user=analyst)

    assert len(access_entries(Action.SUBMISSION_READ)) == 1
    assert access_entries(Action.PII_ACCESS) == []


def test_an_outsider_is_denied_and_logs_nothing(answered, member_factory):
    outsider = member_factory(answered.survey_version.survey.organization, OrgRole.MEMBER)

    with pytest.raises(PermissionDenied):
        read_answers(answered, user=outsider)

    assert access_entries() == []


def test_access_is_logged_once_per_read_not_once_per_answer(answered, member_factory, grant):
    """Per-request granularity: a read touching three answers is one entry."""
    analyst = member_factory(answered.survey_version.survey.organization, OrgRole.MEMBER)
    grant(analyst, answered.survey_version.survey, SurveyRole.ANALYST)

    read_answers(answered, user=analyst)

    assert len(access_entries()) == 1


def test_uuid_primary_keys_are_stored_in_object_pk(survey):
    """LogEntry.object_id is a BigIntegerField and cannot hold a UUID; the
    char column takes it instead, and get_for_object knows to look there."""
    entry = LogEntry.objects.get_for_object(survey).first()

    assert entry.object_id is None
    assert entry.object_pk == str(survey.pk)
