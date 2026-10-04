import pytest
from rest_framework.test import APIClient

from accounts.models import Membership
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion
from surveys.tests.factories import choice, fid

OrgRole = Membership.OrgRole
SurveyRole = SurveyAccess.SurveyRole
pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def as_user(api):
    def login(user):
        api.force_authenticate(user=user)
        return api

    return login


@pytest.fixture
def admin(org, member_factory):
    return member_factory(org, OrgRole.ADMIN)


# --- scoping -----------------------------------------------------------------


def test_survey_list_shows_only_what_the_user_can_see(as_user, org, member_factory, grant):
    mine = Survey.objects.create(organization=org, name="Mine", slug="mine")
    Survey.objects.create(organization=org, name="Theirs", slug="theirs")

    user = member_factory(org, OrgRole.MEMBER)
    grant(user, mine, SurveyRole.VIEWER)

    response = as_user(user).get(f"/api/v1/organizations/{org.id}/surveys/")

    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["Mine"]


def test_invisible_survey_is_404_not_403(as_user, org, member_factory):
    """A 403 would confirm the id exists and leak other tenants' surveys."""
    survey = Survey.objects.create(organization=org, name="Secret", slug="secret")
    outsider = member_factory(org, OrgRole.MEMBER)

    response = as_user(outsider).get(f"/api/v1/surveys/{survey.id}/")

    assert response.status_code == 404


def test_other_organizations_surveys_are_invisible(as_user, org, other_org, member_factory):
    theirs = Survey.objects.create(organization=other_org, name="Theirs", slug="t")
    admin = member_factory(org, OrgRole.ADMIN)

    assert as_user(admin).get(f"/api/v1/surveys/{theirs.id}/").status_code == 404


def test_anonymous_access_is_rejected(api, survey):
    assert api.get(f"/api/v1/surveys/{survey.id}/").status_code in (401, 403)


def test_organization_list_shows_only_memberships(as_user, org, other_org, member_factory):
    user = member_factory(org, OrgRole.MEMBER)

    body = as_user(user).get("/api/v1/organizations/").json()

    assert [o["slug"] for o in body] == ["acme"]
    assert body[0]["role"] == OrgRole.MEMBER


# --- capability gating -------------------------------------------------------


def test_admin_can_create_a_survey(as_user, org, admin):
    response = as_user(admin).post(
        f"/api/v1/organizations/{org.id}/surveys/", {"name": "NPS", "slug": "nps"}, format="json"
    )

    assert response.status_code == 201
    assert Survey.objects.filter(slug="nps").exists()


def test_member_cannot_create_a_survey(as_user, org, member_factory):
    user = member_factory(org, OrgRole.MEMBER)

    response = as_user(user).post(
        f"/api/v1/organizations/{org.id}/surveys/", {"name": "NPS", "slug": "nps"}, format="json"
    )

    assert response.status_code == 403


def test_viewer_cannot_edit_a_survey(as_user, survey, member_factory, grant):
    viewer = member_factory(survey.organization, OrgRole.MEMBER)
    grant(viewer, survey, SurveyRole.VIEWER)

    response = as_user(viewer).patch(
        f"/api/v1/surveys/{survey.id}/", {"name": "Renamed"}, format="json"
    )

    assert response.status_code == 403


def test_editor_can_edit_a_survey(as_user, survey, member_factory, grant):
    editor = member_factory(survey.organization, OrgRole.MEMBER)
    grant(editor, survey, SurveyRole.EDITOR)

    response = as_user(editor).patch(
        f"/api/v1/surveys/{survey.id}/", {"name": "Renamed"}, format="json"
    )

    assert response.status_code == 200
    survey.refresh_from_db()
    assert survey.name == "Renamed"


def test_analyst_cannot_edit_the_survey_they_analyse(as_user, survey, member_factory, grant):
    analyst = member_factory(survey.organization, OrgRole.MEMBER)
    grant(analyst, survey, SurveyRole.ANALYST)

    assert as_user(analyst).get(f"/api/v1/surveys/{survey.id}/").status_code == 200
    assert (
        as_user(analyst)
        .patch(f"/api/v1/surveys/{survey.id}/", {"name": "x"}, format="json")
        .status_code
        == 403
    )


# --- versions and sections ---------------------------------------------------


def test_creating_the_first_version_opens_a_draft(as_user, survey, admin):
    response = as_user(admin).post(f"/api/v1/surveys/{survey.id}/versions/", format="json")

    assert response.status_code == 201
    assert response.json()["version_number"] == 1
    assert response.json()["status"] == "draft"


def test_a_later_version_is_seeded_from_the_published_one(as_user, survey, admin, draft):
    """v2 inherits v1's sections, so field ids carry across versions."""
    field_id = fid()
    Section.objects.create(
        version=draft, key="s1", title="One", order=1, content={field_id: choice()}
    )
    as_user(admin).post(f"/api/v1/versions/{draft.id}/publish/")

    response = as_user(admin).post(f"/api/v1/surveys/{survey.id}/versions/", format="json")

    assert response.json()["version_number"] == 2
    v2 = SurveyVersion.objects.get(id=response.json()["id"])
    assert list(v2.sections.first().content) == [field_id]


def test_sections_can_be_added_to_a_draft(as_user, admin, draft):
    response = as_user(admin).post(
        f"/api/v1/versions/{draft.id}/sections/",
        {"key": "s1", "title": "About you", "order": 1, "content": {fid(): choice()}},
        format="json",
    )

    assert response.status_code == 201
    assert draft.sections.count() == 1


def test_sections_of_a_published_version_are_frozen(as_user, admin, draft):
    section = Section.objects.create(
        version=draft, key="s1", title="One", order=1, content={fid(): choice()}
    )
    as_user(admin).post(f"/api/v1/versions/{draft.id}/publish/")

    response = as_user(admin).patch(
        f"/api/v1/sections/{section.id}/", {"title": "sneaky"}, format="json"
    )

    assert response.status_code == 400
    assert "frozen" in str(response.json())


# --- publish -----------------------------------------------------------------


def test_publishing_returns_the_assembled_schema(as_user, admin, draft):
    field_id = fid()
    Section.objects.create(
        version=draft, key="s1", title="One", order=1, content={field_id: choice()}
    )

    response = as_user(admin).post(f"/api/v1/versions/{draft.id}/publish/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["schema"]["eval_order"] == [field_id]


def test_publishing_an_invalid_draft_returns_the_errors(as_user, admin, draft):
    Section.objects.create(
        version=draft, key="s1", title="One", order=1, content={"not-a-uuid": choice()}
    )

    response = as_user(admin).post(f"/api/v1/versions/{draft.id}/publish/")

    assert response.status_code == 400
    assert any("UUID" in e for e in response.json()["errors"])


def test_an_editor_may_publish_but_a_viewer_may_not(as_user, survey, member_factory, grant, draft):
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={fid(): choice()})
    viewer = member_factory(survey.organization, OrgRole.MEMBER)
    grant(viewer, survey, SurveyRole.VIEWER)
    editor = member_factory(survey.organization, OrgRole.MEMBER)
    grant(editor, survey, SurveyRole.EDITOR)

    assert as_user(viewer).post(f"/api/v1/versions/{draft.id}/publish/").status_code == 403
    assert as_user(editor).post(f"/api/v1/versions/{draft.id}/publish/").status_code == 200


def test_publishing_a_version_of_an_invisible_survey_is_404(as_user, org, member_factory, draft):
    outsider = member_factory(org, OrgRole.MEMBER)

    assert as_user(outsider).post(f"/api/v1/versions/{draft.id}/publish/").status_code == 404


def test_version_list_endpoints_are_scoped(as_user, survey, org, member_factory):
    outsider = member_factory(org, OrgRole.MEMBER)

    assert as_user(outsider).get(f"/api/v1/surveys/{survey.id}/versions/").status_code == 404


def test_duplicate_survey_slug_is_a_field_error(as_user, org, admin):
    """DRF builds uniqueness validators from Meta.unique_together only, never
    from Meta.constraints. Every constraint in this project is a
    UniqueConstraint, so without explicit validation the duplicate reaches
    Postgres and the client sees a 500."""
    url = f"/api/v1/organizations/{org.id}/surveys/"
    as_user(admin).post(url, {"name": "First", "slug": "nps"}, format="json")

    response = as_user(admin).post(url, {"name": "Second", "slug": "nps"}, format="json")

    assert response.status_code == 400
    assert "slug" in response.json()


def test_the_same_slug_is_fine_in_another_organization(as_user, org, other_org, member_factory):
    admin_a = member_factory(org, OrgRole.ADMIN)
    admin_b = member_factory(other_org, OrgRole.ADMIN)

    first = as_user(admin_a).post(
        f"/api/v1/organizations/{org.id}/surveys/", {"name": "NPS", "slug": "nps"}, format="json"
    )
    second = as_user(admin_b).post(
        f"/api/v1/organizations/{other_org.id}/surveys/",
        {"name": "NPS", "slug": "nps"},
        format="json",
    )

    assert first.status_code == second.status_code == 201


def test_renaming_a_survey_to_its_own_slug_is_allowed(as_user, org, admin):
    created = (
        as_user(admin)
        .post(
            f"/api/v1/organizations/{org.id}/surveys/",
            {"name": "NPS", "slug": "nps"},
            format="json",
        )
        .json()
    )

    response = as_user(admin).patch(
        f"/api/v1/surveys/{created['id']}/", {"name": "NPS 2026", "slug": "nps"}, format="json"
    )

    assert response.status_code == 200


def test_duplicate_section_key_is_a_field_error(as_user, admin, draft):
    url = f"/api/v1/versions/{draft.id}/sections/"
    as_user(admin).post(url, {"key": "s1", "title": "One", "order": 1}, format="json")

    response = as_user(admin).post(url, {"key": "s1", "title": "Two", "order": 2}, format="json")

    assert response.status_code == 400
    assert "key" in response.json()


def test_an_unmirrored_constraint_is_a_conflict_not_a_server_error(as_user, survey, user_factory):
    """Safety net: any constraint a serializer does not know about should
    still reach the client as a conflict rather than a 500."""
    from django.db import IntegrityError

    from core.api import exception_handler

    response = exception_handler(IntegrityError("duplicate key"), {})

    assert response.status_code == 409


def test_a_survey_without_responses_can_be_deleted(as_user, org, admin):
    created = (
        as_user(admin)
        .post(
            f"/api/v1/organizations/{org.id}/surveys/",
            {"name": "Unused", "slug": "unused"},
            format="json",
        )
        .json()
    )

    response = as_user(admin).delete(f"/api/v1/surveys/{created['id']}/")

    assert response.status_code == 204
    assert not Survey.objects.filter(id=created["id"]).exists()


# --- addressing a survey by slug ---------------------------------------------


@pytest.mark.django_db
def test_a_survey_can_be_fetched_by_slug(as_user, org, admin, survey):
    """The slug was stored, validated and returned, but nothing ever looked
    one up -- the field was decoration until this route existed."""
    by_slug = as_user(admin).get(f"/api/v1/o/{org.slug}/surveys/{survey.slug}/")

    assert by_slug.status_code == 200
    assert by_slug.json()["id"] == str(survey.id)


@pytest.mark.django_db
def test_the_slug_route_is_scoped_to_one_organization(as_user, org, other_org, admin, survey):
    """A slug is unique per organization, not globally. Looking one up under
    an organization that does not own it must not reach across."""
    response = as_user(admin).get(f"/api/v1/o/{other_org.slug}/surveys/{survey.slug}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_an_unknown_slug_is_a_404(as_user, org, admin):
    assert as_user(admin).get(f"/api/v1/o/{org.slug}/surveys/nope/").status_code == 404


@pytest.mark.django_db
def test_the_slug_route_obeys_the_same_scoping_as_the_id_route(
    as_user, org, survey, member_factory
):
    """A member with no grant cannot see it by name either -- 404, not 403,
    so a guessed slug cannot confirm the survey exists."""
    outsider = member_factory(org, OrgRole.MEMBER)

    response = as_user(outsider).get(f"/api/v1/o/{org.slug}/surveys/{survey.slug}/")

    assert response.status_code == 404


def test_every_capability_scoped_view_enforces_a_capability():
    """Regression guard. These views were briefly authorizing everything
    because the mixin left permission_classes at the project default of
    IsAuthenticated alone -- a view is not safe just because it looks scoped.

    Walks every app, not just surveys: the guard existed for one module while
    scoped views were being added to others, which is how it would miss the
    next occurrence of the bug it was written for.
    """
    import importlib
    import inspect

    from core.api import CapabilityScopedMixin, HasCapability

    scoped = []
    for app in ("accounts", "surveys", "responses", "analytics", "exports", "invitations"):
        module = importlib.import_module(f"{app}.views")
        # Concrete views only: the intermediate mixins are abstract and
        # declare no capabilities of their own.
        scoped += [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, CapabilityScopedMixin)
            and hasattr(obj, "as_view")
            and obj.__module__ == module.__name__
        ]

    assert len(scoped) >= 10, f"only found {len(scoped)} scoped views"
    for view in scoped:
        assert HasCapability in view.permission_classes, view.__name__
        assert view.read_perm and view.write_perm, view.__name__


# --- constraint violations surface as field errors, not 500s -----------------


def test_a_survey_with_responses_cannot_be_deleted(as_user, live_survey, member_factory, ids):
    """PROTECT is deliberate: deleting the version would destroy the schema
    those answers need in order to mean anything. The client should be told
    that plainly rather than getting a 500."""
    from responses.services import save_answers, start_submission

    submission = start_submission(live_survey)
    save_answers(submission, {ids["country"]: "eg", ids["age"]: 30}, complete=True)

    admin = member_factory(live_survey.survey.organization, OrgRole.ADMIN)
    response = as_user(admin).delete(f"/api/v1/surveys/{live_survey.survey_id}/")

    assert response.status_code == 409
    assert "Archive it instead" in str(response.json())
