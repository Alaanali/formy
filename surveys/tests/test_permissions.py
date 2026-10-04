import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import Membership
from surveys.models import Survey, SurveyAccess
from surveys.permissions import (
    ROLE_PERMISSIONS,
    Perm,
    effective_role,
    permissions_for,
    visible_surveys,
)

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole


# --- role resolution ---------------------------------------------------------


@pytest.mark.django_db
def test_org_admin_has_authority_without_any_survey_grant(survey, member_factory):
    admin = member_factory(survey.organization, OrgRole.ADMIN)
    assert effective_role(admin, survey) == OrgRole.ADMIN


@pytest.mark.django_db
def test_plain_member_has_no_role_until_granted(survey, member_factory, grant):
    user = member_factory(survey.organization, OrgRole.MEMBER)
    assert effective_role(user, survey) is None

    grant(user, survey, SurveyRole.VIEWER)
    user._effective_role_cache.clear()
    assert effective_role(user, survey) == SurveyRole.VIEWER


@pytest.mark.django_db
def test_non_member_has_no_role_even_with_a_grant(survey, user_factory, grant):
    """A grant alone is not access: the user must belong to the owning org."""
    outsider = user_factory()
    grant(outsider, survey, SurveyRole.ANALYST)

    assert effective_role(outsider, survey) is None


@pytest.mark.django_db
def test_anonymous_user_has_no_role(survey):
    from django.contrib.auth.models import AnonymousUser

    assert effective_role(AnonymousUser(), survey) is None


# --- the capability matrix ---------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "perm", "expected"),
    [
        (OrgRole.OWNER, Perm.MEMBER_MANAGE, True),
        (OrgRole.ADMIN, Perm.MEMBER_MANAGE, False),  # admins cannot manage members
        (OrgRole.ADMIN, Perm.RESPONSE_VIEW_PII, True),
        (OrgRole.MEMBER, Perm.SURVEY_VIEW, False),
        (SurveyRole.EDITOR, Perm.SURVEY_EDIT, True),
        (SurveyRole.EDITOR, Perm.SURVEY_PUBLISH, True),
        (SurveyRole.EDITOR, Perm.RESPONSE_VIEW, True),
        (SurveyRole.EDITOR, Perm.RESPONSE_VIEW_RAW, False),
        (SurveyRole.EDITOR, Perm.RESPONSE_VIEW_PII, False),
        (SurveyRole.ANALYST, Perm.RESPONSE_VIEW_PII, True),
        (SurveyRole.ANALYST, Perm.RESPONSE_EXPORT, True),
        (SurveyRole.ANALYST, Perm.SURVEY_EDIT, False),
        (SurveyRole.VIEWER, Perm.RESPONSE_VIEW, True),
        (SurveyRole.VIEWER, Perm.RESPONSE_VIEW_RAW, False),
        (SurveyRole.VIEWER, Perm.RESPONSE_VIEW_PII, False),
        (SurveyRole.VIEWER, Perm.RESPONSE_EXPORT, False),
    ],
)
def test_permission_matrix(survey, member_factory, grant, role, perm, expected):
    if role in OrgRole.values:
        user = member_factory(survey.organization, role)
    else:
        user = member_factory(survey.organization, OrgRole.MEMBER)
        grant(user, survey, role)

    assert user.has_perm(perm, survey) is expected


@pytest.mark.django_db
def test_editor_can_build_but_never_reads_an_individual_response(survey, member_factory, grant):
    """The separation an editor/analyst split exists for: someone who builds
    the survey should not automatically read the personal data it collects."""
    editor = member_factory(survey.organization, OrgRole.MEMBER)
    grant(editor, survey, SurveyRole.EDITOR)

    assert editor.has_perm(Perm.SURVEY_EDIT, survey)
    assert not editor.has_perm(Perm.RESPONSE_VIEW_RAW, survey)
    assert not editor.has_perm(Perm.RESPONSE_VIEW_PII, survey)


@pytest.mark.django_db
def test_grant_on_one_survey_gives_nothing_on_another(org, member_factory, grant):
    granted = Survey.objects.create(organization=org, name="A", slug="a")
    other = Survey.objects.create(organization=org, name="B", slug="b")

    analyst = member_factory(org, OrgRole.MEMBER)
    grant(analyst, granted, SurveyRole.ANALYST)

    assert analyst.has_perm(Perm.RESPONSE_VIEW_PII, granted)
    assert not analyst.has_perm(Perm.RESPONSE_VIEW_PII, other)


@pytest.mark.django_db
def test_permission_without_an_object_is_denied(survey, member_factory):
    """There is no survey capability in the abstract -- always scoped."""
    owner = member_factory(survey.organization, OrgRole.OWNER)
    assert owner.has_perm(Perm.SURVEY_EDIT) is False


@pytest.mark.django_db
def test_every_role_is_present_in_the_matrix():
    """A role with no entry would silently resolve to no permissions."""
    declared = set(OrgRole.values) | set(SurveyRole.values)
    assert declared == set(ROLE_PERMISSIONS)


# --- queryset scoping --------------------------------------------------------


@pytest.mark.django_db
def test_member_sees_only_granted_surveys(org, member_factory, grant):
    granted = Survey.objects.create(organization=org, name="A", slug="a")
    Survey.objects.create(organization=org, name="B", slug="b")

    user = member_factory(org, OrgRole.MEMBER)
    grant(user, granted, SurveyRole.VIEWER)

    assert list(visible_surveys(user, org.id)) == [granted]


@pytest.mark.django_db
def test_member_without_grants_sees_nothing(org, member_factory):
    Survey.objects.create(organization=org, name="A", slug="a")
    user = member_factory(org, OrgRole.MEMBER)

    assert list(visible_surveys(user, org.id)) == []


@pytest.mark.django_db
def test_admin_sees_every_survey_in_their_org_only(org, other_org, member_factory):
    mine = Survey.objects.create(organization=org, name="A", slug="a")
    Survey.objects.create(organization=other_org, name="Theirs", slug="theirs")

    admin = member_factory(org, OrgRole.ADMIN)

    assert list(visible_surveys(admin, org.id)) == [mine]
    assert list(visible_surveys(admin, other_org.id)) == []


# --- memoisation -------------------------------------------------------------


@pytest.mark.django_db
def test_role_is_resolved_once_per_user_and_survey(survey, member_factory, grant):
    """Serialising a page of rows must not re-run the role lookup per row."""
    user = member_factory(survey.organization, OrgRole.MEMBER)
    grant(user, survey, SurveyRole.ANALYST)

    with CaptureQueriesContext(connection) as ctx:
        for _ in range(10):
            permissions_for(user, survey)

    assert len(ctx.captured_queries) == 2  # one membership, one grant


# --- superuser asymmetry, documented deliberately ----------------------------


@pytest.mark.django_db
def test_superuser_bypasses_has_perm_but_not_queryset_scoping(org, user_factory):
    """Django short-circuits has_perm for active superusers before any backend
    runs, so a superuser passes every capability check. visible_surveys does
    not honour that, and should not: queryset scoping is tenant isolation, and
    a staff account should have to be granted access like anyone else to appear
    in tenant-facing listings.

    The asymmetry is intentional. It is asserted here so that it stays a known
    property rather than becoming a surprise during a security review.
    """
    survey = Survey.objects.create(organization=org, name="A", slug="a")
    root = user_factory(is_superuser=True, is_staff=True)

    assert root.has_perm(Perm.RESPONSE_VIEW_PII, survey) is True
    assert list(visible_surveys(root, org.id)) == []


# --- organization-scoped capabilities ----------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "expected"),
    [(OrgRole.OWNER, True), (OrgRole.ADMIN, True), (OrgRole.MEMBER, False)],
)
def test_survey_creation_is_an_organization_capability(org, member_factory, role, expected):
    """Creating a survey happens before any survey exists, so it is checked
    against the Organization -- through the same matrix, not a second one."""
    user = member_factory(org, role)
    assert user.has_perm(Perm.SURVEY_CREATE, org) is expected


@pytest.mark.django_db
def test_org_capabilities_do_not_leak_across_organizations(org, other_org, member_factory):
    admin = member_factory(org, OrgRole.ADMIN)

    assert admin.has_perm(Perm.SURVEY_CREATE, org) is True
    assert admin.has_perm(Perm.SURVEY_CREATE, other_org) is False


@pytest.mark.django_db
def test_a_survey_grant_gives_no_organization_capability(org, member_factory, grant):
    """An editor on one survey must not thereby be able to create new ones."""
    survey = Survey.objects.create(organization=org, name="A", slug="a")
    editor = member_factory(org, OrgRole.MEMBER)
    grant(editor, survey, SurveyRole.EDITOR)

    assert editor.has_perm(Perm.SURVEY_EDIT, survey) is True
    assert editor.has_perm(Perm.SURVEY_CREATE, org) is False
