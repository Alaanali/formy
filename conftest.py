import pytest
from django.contrib.auth import get_user_model

from accounts.models import Membership, Organization
from surveys.models import Survey, SurveyAccess, SurveyVersion

User = get_user_model()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme Research", slug="acme")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Globex", slug="globex")


@pytest.fixture
def user_factory(db):
    counter = iter(range(1, 10_000))

    def make(username=None, **kwargs):
        username = username or f"user{next(counter)}"
        return User.objects.create_user(username=username, password="pw", **kwargs)

    return make


@pytest.fixture
def member_factory(db, user_factory):
    """Create a user holding a given org role."""

    def make(organization, role=Membership.OrgRole.MEMBER, user=None):
        user = user or user_factory()
        Membership.objects.create(user=user, organization=organization, role=role)
        return user

    return make


@pytest.fixture
def survey(org):
    return Survey.objects.create(organization=org, name="NPS 2026", slug="nps-2026")


@pytest.fixture
def grant():
    """Give a user a role on a single survey."""

    def make(user, survey, role=SurveyAccess.SurveyRole.VIEWER):
        return SurveyAccess.objects.create(user=user, survey=survey, role=role)

    return make


@pytest.fixture
def draft(survey):
    return SurveyVersion.objects.create_draft(survey)
