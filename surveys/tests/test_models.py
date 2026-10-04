import pytest
from django.db.utils import IntegrityError

from surveys.models import Section, Survey, SurveyAccess


@pytest.mark.django_db
def test_survey_slug_is_unique_within_an_org_only(org, other_org):
    Survey.objects.create(organization=org, name="NPS", slug="nps")

    with pytest.raises(IntegrityError):
        Survey.objects.create(organization=org, name="NPS again", slug="nps")


@pytest.mark.django_db
def test_two_orgs_may_reuse_the_same_slug(org, other_org):
    Survey.objects.create(organization=org, name="NPS", slug="nps")
    Survey.objects.create(organization=other_org, name="NPS", slug="nps")

    assert Survey.objects.filter(slug="nps").count() == 2


@pytest.mark.django_db
def test_user_has_at_most_one_grant_per_survey(survey, user_factory):
    user = user_factory()
    SurveyAccess.objects.create(user=user, survey=survey, role=SurveyAccess.SurveyRole.VIEWER)

    with pytest.raises(IntegrityError):
        SurveyAccess.objects.create(user=user, survey=survey, role=SurveyAccess.SurveyRole.ANALYST)


@pytest.mark.django_db
def test_members_m2m_resolves_through_survey_access(survey, user_factory, grant):
    analyst = user_factory()
    viewer = user_factory()
    grant(analyst, survey, SurveyAccess.SurveyRole.ANALYST)
    grant(viewer, survey, SurveyAccess.SurveyRole.VIEWER)

    assert set(survey.members.all()) == {analyst, viewer}
    assert list(analyst.accessible_surveys.all()) == [survey]


@pytest.mark.django_db
def test_survey_access_has_a_single_link_to_user(survey):
    """One FK to User, so the M2M needs no through_fields. Grant provenance
    lives in the audit log rather than in a second column here."""
    user_fks = [
        f.name
        for f in SurveyAccess._meta.get_fields()
        if getattr(f, "related_model", None) is not None
        and f.related_model._meta.label_lower == "auth.user"
    ]

    assert user_fks == ["user"]


@pytest.mark.django_db
def test_revoking_access_removes_membership_not_the_survey(survey, user_factory, grant):
    viewer = user_factory()
    access = grant(viewer, survey)
    access.delete()

    survey.refresh_from_db()
    assert list(survey.members.all()) == []


@pytest.mark.django_db
def test_section_keys_are_unique_within_a_version(draft):
    """The invariant that replaced publish-time duplicate-key validation.

    The validator used to check this, which was unreachable: the constraint
    refuses the second row long before a document is ever assembled.
    """
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={})

    with pytest.raises(IntegrityError):
        Section.objects.create(version=draft, key="s1", title="Duplicate", order=2, content={})
