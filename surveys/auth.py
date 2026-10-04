from django.contrib.auth.backends import BaseBackend

from accounts.models import Organization
from surveys.permissions import permissions_for, permissions_for_org, resolve_survey


class SurveyPermissionBackend(BaseBackend):
    def has_perm(self, user_obj, perm, obj=None) -> bool:
        # Object-scoped only: there is no survey capability without a survey.
        if obj is None or not getattr(user_obj, "is_authenticated", False):
            return False

        if isinstance(obj, Organization):
            return perm in permissions_for_org(user_obj, obj)

        # Survey scope first: a Survey also names an organization, and its
        # own grants must decide it. permissions_for already folds in
        # org-wide roles.
        survey = resolve_survey(obj)
        if survey is not None:
            return perm in permissions_for(user_obj, survey)

        # Otherwise an object that names an organization is governed by it --
        # a Membership, for instance, which belongs to no survey.
        organization = getattr(obj, "organization", None)
        if isinstance(organization, Organization):
            return perm in permissions_for_org(user_obj, organization)

        return False
