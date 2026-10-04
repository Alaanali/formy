import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.utils import timezone

from surveys.models import Section, Survey, SurveyVersion


@pytest.mark.django_db
def test_create_draft_numbers_versions_sequentially(survey):
    first = SurveyVersion.objects.create_draft(survey)
    assert first.version_number == 1

    first.status = SurveyVersion.Status.PUBLISHED
    first.save()

    second = SurveyVersion.objects.create_draft(survey)
    assert second.version_number == 2


@pytest.mark.django_db
def test_a_survey_may_have_only_one_draft(survey, draft):
    with pytest.raises(IntegrityError):
        SurveyVersion.objects.create(
            survey=survey, version_number=99, status=SurveyVersion.Status.DRAFT
        )


@pytest.mark.django_db
def test_a_survey_may_have_many_published_versions(survey):
    for n in (1, 2, 3):
        SurveyVersion.objects.create(
            survey=survey,
            version_number=n,
            status=SurveyVersion.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    assert survey.versions.published().count() == 3


@pytest.mark.django_db
def test_version_numbers_are_unique_per_survey(survey, org):
    SurveyVersion.objects.create(
        survey=survey, version_number=1, status=SurveyVersion.Status.PUBLISHED
    )
    with pytest.raises(IntegrityError):
        SurveyVersion.objects.create(
            survey=survey, version_number=1, status=SurveyVersion.Status.ARCHIVED
        )


@pytest.mark.django_db
def test_two_surveys_number_versions_independently(org):
    a = Survey.objects.create(organization=org, name="A", slug="a")
    b = Survey.objects.create(organization=org, name="B", slug="b")

    assert SurveyVersion.objects.create_draft(a).version_number == 1
    assert SurveyVersion.objects.create_draft(b).version_number == 1


# --- the freeze guard --------------------------------------------------------


@pytest.mark.django_db
def test_sections_are_editable_while_the_version_is_a_draft(draft):
    section = Section.objects.create(version=draft, key="s1", title="About you", order=1)
    section.title = "About you (edited)"
    section.save()

    section.refresh_from_db()
    assert section.title == "About you (edited)"


@pytest.mark.django_db
def test_published_version_rejects_writes_to_its_sections(draft):
    """The reason two representations are safe: once a version is published
    its authoring rows cannot drift from the schema assembled out of them."""
    section = Section.objects.create(version=draft, key="s1", title="About you")

    draft.status = SurveyVersion.Status.PUBLISHED
    draft.save()
    section.version.refresh_from_db()

    section.title = "sneaky edit"
    with pytest.raises(ValidationError, match="frozen"):
        section.save()


@pytest.mark.django_db
def test_published_version_rejects_new_sections(draft):
    draft.status = SurveyVersion.Status.PUBLISHED
    draft.save()

    with pytest.raises(ValidationError, match="frozen"):
        Section.objects.create(version=draft, key="late", title="Too late")


@pytest.mark.django_db
def test_published_version_rejects_section_deletion(draft):
    section = Section.objects.create(version=draft, key="s1", title="About you")

    draft.status = SurveyVersion.Status.PUBLISHED
    draft.save()
    section.version.refresh_from_db()

    with pytest.raises(ValidationError, match="frozen"):
        section.delete()


@pytest.mark.django_db
def test_queryset_update_bypasses_the_guard(draft):
    """Documents a known limit: .update() never calls save(), so the model
    guard cannot see it. The frozen schema column is the guarantee that
    matters -- nothing reads Section rows after publish. Full enforcement
    would need a database trigger (see DESIGN.md)."""
    Section.objects.create(version=draft, key="s1", title="About you")
    draft.status = SurveyVersion.Status.PUBLISHED
    draft.save()

    Section.objects.filter(version=draft).update(title="bypassed")

    assert Section.objects.get(version=draft).title == "bypassed"


@pytest.mark.django_db
def test_section_keys_are_unique_within_a_version(draft):
    Section.objects.create(version=draft, key="s1", title="One")
    with pytest.raises(IntegrityError):
        Section.objects.create(version=draft, key="s1", title="Duplicate")


@pytest.mark.django_db
def test_sections_order_by_their_order_field(draft):
    Section.objects.create(version=draft, key="c", title="C", order=3)
    Section.objects.create(version=draft, key="a", title="A", order=1)
    Section.objects.create(version=draft, key="b", title="B", order=2)

    assert [s.key for s in draft.sections.all()] == ["a", "b", "c"]


@pytest.mark.django_db
def test_draft_creation_locks_the_survey_row(survey):
    """Two operators clicking "new draft" at once must not race.

    F() cannot express this numbering: it references a column of the row
    being written, and this is an INSERT whose value comes from an aggregate
    over sibling rows. Raw INSERT ... SELECT MAX()+1 would not help either,
    since under READ COMMITTED both transactions read the same maximum. The
    survey row is locked instead, so the calls serialise.

    Asserted by inspecting the SQL rather than with threads: a threaded test
    needs transaction=True, which commits its fixtures and pollutes a reused
    test database. Real concurrency is covered by `make perf`, which fires
    40 simultaneous submissions at a running server.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        SurveyVersion.objects.create_draft(survey)

    locking = [q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"].upper()]

    assert locking, "draft creation did not lock the survey row"
    assert "surveys_survey" in locking[0]
    # The versions themselves are not locked, so reading an existing version
    # is never blocked by someone opening a draft.
    assert "surveys_surveyversion" not in locking[0]
