import pytest
from django.db.utils import IntegrityError

from accounts.models import Membership, Organization


@pytest.mark.django_db
def test_organization_slug_is_unique():
    Organization.objects.create(name="Acme", slug="acme")
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="Acme Duplicate", slug="acme")


@pytest.mark.django_db
def test_user_has_at_most_one_membership_per_org(org, user_factory):
    user = user_factory()
    Membership.objects.create(user=user, organization=org, role=Membership.OrgRole.ADMIN)

    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, organization=org, role=Membership.OrgRole.MEMBER)


@pytest.mark.django_db
def test_same_user_can_belong_to_several_orgs(org, other_org, user_factory):
    user = user_factory()
    Membership.objects.create(user=user, organization=org, role=Membership.OrgRole.ADMIN)
    Membership.objects.create(user=user, organization=other_org, role=Membership.OrgRole.MEMBER)

    assert user.memberships.count() == 2


@pytest.mark.django_db
def test_ids_are_uuid7_and_time_ordered(org):
    """UUIDv7 keeps insert locality; a v4 id would scatter across the index."""
    first = Organization.objects.create(name="A", slug="a")
    second = Organization.objects.create(name="B", slug="b")

    assert first.id.version == 7
    assert first.id < second.id
