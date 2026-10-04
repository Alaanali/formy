import uuid

import pytest
from django.contrib.auth import get_user_model

from accounts.models import Membership, Organization
from surveys.document import FieldType
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion
from surveys.publish import publish
from surveys.tests.factories import choice, eq, field

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


# --- a survey exercising every feature the response path must handle ---------
# A conditional field, a cross-section dependency, filtered options, a
# sensitive field and a conditionally required one. Shared because the
# response, analytics and audit suites all need the same shape.

COUNTRY = str(uuid.uuid7())
AGE = str(uuid.uuid7())
CITY = str(uuid.uuid7())
NATIONAL_ID = str(uuid.uuid7())
COMMENTS = str(uuid.uuid7())


@pytest.fixture
def ids():
    """Field ids as strings: what a client sends and what a schema stores."""
    return {
        "country": COUNTRY,
        "age": AGE,
        "city": CITY,
        "national_id": NATIONAL_ID,
        "comments": COMMENTS,
    }


@pytest.fixture
def uid(ids):
    """The same ids as UUIDs: what the parsed document and the evaluator use."""
    return {name: uuid.UUID(value) for name, value in ids.items()}


@pytest.fixture
def live_survey(draft):
    Section.objects.create(
        version=draft,
        key="about",
        title="About you",
        order=1,
        content={
            COUNTRY: choice(values=("sa", "eg"), label="Country", required=True),
            AGE: field(FieldType.NUMBER, label="Age", min=0, max=120),
            NATIONAL_ID: field(FieldType.TEXT, label="National ID", sensitive=True),
        },
    )
    Section.objects.create(
        version=draft,
        key="location",
        title="Location",
        order=2,
        content={
            CITY: {
                "type": FieldType.DROPDOWN,
                "label": "City",
                # Both fields in this section depend on an answer in the
                # previous one, so the section as a whole disappears for
                # anyone who did not pick Saudi Arabia.
                "visible": eq(COUNTRY, "sa"),
                # Conditionally required: only for respondents 21 and over.
                "required": {"any": [{"field": AGE, "op": "gte", "value": 21}]},
                "options": [
                    {"value": "riyadh", "label": "Riyadh", "when": eq(COUNTRY, "sa")},
                    {"value": "cairo", "label": "Cairo", "when": eq(COUNTRY, "eg")},
                ],
            },
            COMMENTS: field(
                FieldType.TEXTAREA, label="Comments", max_length=50, visible=eq(COUNTRY, "sa")
            ),
        },
    )
    return publish(draft)
