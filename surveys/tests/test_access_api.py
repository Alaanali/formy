import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Membership
from surveys.models import SurveyAccess

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole


@pytest.fixture
def client_for():
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _client


@pytest.mark.django_db
def test_an_owner_can_grant_access_to_a_survey(survey, member_factory, client_for):
    owner = member_factory(survey.organization, OrgRole.OWNER)
    analyst = member_factory(survey.organization, OrgRole.MEMBER)

    response = client_for(owner).post(
        reverse("surveys:access-list", args=[survey.id]),
        {"user": analyst.id, "role": SurveyRole.ANALYST},
        format="json",
    )

    assert response.status_code == 201
    assert SurveyAccess.objects.get(user=analyst, survey=survey).role == SurveyRole.ANALYST


@pytest.mark.django_db
def test_a_granted_analyst_can_then_see_the_survey(
    survey, member_factory, client_for, user_factory
):
    """The grant is not cosmetic: it is what makes the survey visible."""
    owner = member_factory(survey.organization, OrgRole.OWNER)
    analyst = member_factory(survey.organization, OrgRole.MEMBER)

    detail = reverse("surveys:survey-detail", args=[survey.id])
    assert client_for(analyst).get(detail).status_code == 404

    client_for(owner).post(
        reverse("surveys:access-list", args=[survey.id]),
        {"user": analyst.id, "role": SurveyRole.ANALYST},
        format="json",
    )

    assert client_for(analyst).get(detail).status_code == 200


@pytest.mark.django_db
def test_an_editor_cannot_widen_access(survey, member_factory, client_for, grant):
    """An editor builds the survey but must not be able to hand someone else
    the capability to read responses the editor cannot read themselves."""
    editor = member_factory(survey.organization, OrgRole.MEMBER)
    grant(editor, survey, SurveyRole.EDITOR)
    colleague = member_factory(survey.organization, OrgRole.MEMBER)

    response = client_for(editor).post(
        reverse("surveys:access-list", args=[survey.id]),
        {"user": colleague.id, "role": SurveyRole.ANALYST},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_revoking_a_grant_removes_visibility(
    survey, member_factory, client_for, grant, user_factory
):
    owner = member_factory(survey.organization, OrgRole.OWNER)
    analyst = member_factory(survey.organization, OrgRole.MEMBER)
    access = grant(analyst, survey, SurveyRole.ANALYST)

    deleted = client_for(owner).delete(reverse("surveys:access-detail", args=[access.id]))

    assert deleted.status_code == 204
    detail = reverse("surveys:survey-detail", args=[survey.id])
    assert client_for(analyst).get(detail).status_code == 404


@pytest.mark.django_db
def test_grants_of_another_tenants_survey_are_404(
    survey, other_org, member_factory, client_for, user_factory
):
    outsider = member_factory(other_org, OrgRole.OWNER)

    response = client_for(outsider).get(reverse("surveys:access-list", args=[survey.id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_only_an_owner_may_manage_members(org, member_factory, client_for, user_factory):
    """MEMBER_MANAGE is the only capability separating owner from admin, so
    without this endpoint checking it the two roles were indistinguishable."""
    owner = member_factory(org, OrgRole.OWNER)
    admin = member_factory(org, OrgRole.ADMIN)
    url = reverse("accounts:membership-list", args=[org.id])

    assert client_for(owner).get(url).status_code == 200
    assert client_for(admin).get(url).status_code == 403


@pytest.mark.django_db
def test_an_owner_can_add_and_remove_a_member(org, member_factory, client_for, user_factory):
    owner = member_factory(org, OrgRole.OWNER)
    newcomer = user_factory()

    created = client_for(owner).post(
        reverse("accounts:membership-list", args=[org.id]),
        {"user": newcomer.id, "role": OrgRole.MEMBER},
        format="json",
    )
    assert created.status_code == 201

    membership = Membership.objects.get(user=newcomer, organization=org)
    removed = client_for(owner).delete(reverse("accounts:membership-detail", args=[membership.id]))
    assert removed.status_code == 204
    assert not Membership.objects.filter(pk=membership.pk).exists()


@pytest.mark.django_db
def test_a_grant_to_a_non_member_is_refused(survey, other_org, member_factory, client_for):
    """A grant to someone outside the organization confers nothing, because
    effective_role resolves an org role first. Storing one anyway used to
    make the survey visible to the queryset while every capability was still
    refused -- so the outsider got a 403, which confirms the id exists."""
    owner = member_factory(survey.organization, OrgRole.OWNER)
    outsider = member_factory(other_org, OrgRole.MEMBER)

    response = client_for(owner).post(
        reverse("surveys:access-list", args=[survey.id]),
        {"user": outsider.id, "role": SurveyRole.ANALYST},
        format="json",
    )

    assert response.status_code == 400
    assert "not a member" in str(response.json())


@pytest.mark.django_db
def test_a_stray_grant_still_yields_404_not_403(survey, other_org, member_factory, client_for):
    """Belt and braces for the same hole: even if a grant row exists for a
    non-member, the survey must not become visible to them."""
    outsider = member_factory(other_org, OrgRole.MEMBER)
    SurveyAccess.objects.create(user=outsider, survey=survey, role=SurveyRole.ANALYST)

    response = client_for(outsider).get(reverse("surveys:survey-detail", args=[survey.id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_last_owner_cannot_be_removed(org, member_factory, client_for):
    """Owners alone hold MEMBER_MANAGE and ACCESS_GRANT, so an organization
    with none is one nobody can administer, with no way back via the API."""
    owner = member_factory(org, OrgRole.OWNER)
    membership = Membership.objects.get(user=owner, organization=org)

    response = client_for(owner).delete(reverse("accounts:membership-detail", args=[membership.id]))

    assert response.status_code == 400
    assert "only owner" in str(response.json())
    assert Membership.objects.filter(pk=membership.pk).exists()


@pytest.mark.django_db
def test_the_last_owner_cannot_demote_themselves(org, member_factory, client_for):
    owner = member_factory(org, OrgRole.OWNER)
    membership = Membership.objects.get(user=owner, organization=org)

    response = client_for(owner).patch(
        reverse("accounts:membership-detail", args=[membership.id]),
        {"role": OrgRole.MEMBER},
        format="json",
    )

    assert response.status_code == 400
    membership.refresh_from_db()
    assert membership.role == OrgRole.OWNER


@pytest.mark.django_db
def test_an_owner_may_step_down_once_another_exists(org, member_factory, client_for):
    first = member_factory(org, OrgRole.OWNER)
    member_factory(org, OrgRole.OWNER)
    membership = Membership.objects.get(user=first, organization=org)

    response = client_for(first).patch(
        reverse("accounts:membership-detail", args=[membership.id]),
        {"role": OrgRole.MEMBER},
        format="json",
    )

    assert response.status_code == 200
