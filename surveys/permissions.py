from enum import StrEnum

from accounts.models import Membership, Organization
from surveys.models import Survey, SurveyAccess


class Perm(StrEnum):
    SURVEY_CREATE = "survey.create"  # checked against an Organization
    SURVEY_VIEW = "survey.view"
    SURVEY_EDIT = "survey.edit"
    SURVEY_PUBLISH = "survey.publish"

    RESPONSE_VIEW = "response.view"  # aggregates only
    RESPONSE_VIEW_RAW = "response.view_raw"  # individual submissions
    RESPONSE_VIEW_PII = "response.view_pii"  # decrypted sensitive answers
    RESPONSE_EXPORT = "response.export"

    MEMBER_MANAGE = "member.manage"  # org membership
    ACCESS_GRANT = "access.grant"  # per-survey grants


_ALL: frozenset[str] = frozenset(Perm)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Membership.OrgRole.OWNER: _ALL,
    Membership.OrgRole.ADMIN: _ALL - {Perm.MEMBER_MANAGE},
    # A member holds no survey capability until granted one on a survey.
    Membership.OrgRole.MEMBER: frozenset(),
    SurveyAccess.SurveyRole.EDITOR: frozenset(
        {
            Perm.SURVEY_VIEW,
            Perm.SURVEY_EDIT,
            Perm.SURVEY_PUBLISH,
            Perm.RESPONSE_VIEW,
        }
    ),
    # An editor builds surveys and reads aggregates but cannot open an
    # individual response or decrypt PII.
    SurveyAccess.SurveyRole.ANALYST: frozenset(
        {
            Perm.SURVEY_VIEW,
            Perm.RESPONSE_VIEW,
            Perm.RESPONSE_VIEW_RAW,
            Perm.RESPONSE_VIEW_PII,
            Perm.RESPONSE_EXPORT,
        }
    ),
    SurveyAccess.SurveyRole.VIEWER: frozenset(
        {
            Perm.SURVEY_VIEW,
            Perm.RESPONSE_VIEW,
        }
    ),
}

ORG_WIDE_ROLES = (Membership.OrgRole.OWNER, Membership.OrgRole.ADMIN)


def resolve_survey(obj) -> Survey | None:
    """Map any object in the survey tree to the Survey that governs it."""
    if isinstance(obj, Survey):
        return obj
    survey = getattr(obj, "survey", None)
    if isinstance(survey, Survey):
        return survey
    # Section -> version -> survey, Submission -> survey_version -> survey.
    for attr in ("version", "survey_version"):
        parent = getattr(obj, attr, None)
        if parent is not None:
            return getattr(parent, "survey", None)
    return None


def org_role(user, organization_id) -> str | None:
    """The user's org-wide role, memoised on the user for the request."""
    cache = getattr(user, "_org_role_cache", None)
    if cache is None:
        cache = user._org_role_cache = {}
    if organization_id not in cache:
        cache[organization_id] = (
            Membership.objects.filter(user=user, organization_id=organization_id)
            .values_list("role", flat=True)
            .first()
        )
    return cache[organization_id]


def effective_role(user, survey: Survey) -> str | None:
    """OrgRole for org-wide authority, SurveyRole for a grant, None for neither."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    cache = getattr(user, "_effective_role_cache", None)
    if cache is None:
        cache = user._effective_role_cache = {}
    if survey.id in cache:
        return cache[survey.id]

    role = org_role(user, survey.organization_id)
    if role not in ORG_WIDE_ROLES:
        role = (
            None
            if role is None  # not a member of the owning org at all
            else SurveyAccess.objects.filter(user=user, survey=survey)
            .values_list("role", flat=True)
            .first()
        )

    cache[survey.id] = role
    return role


def permissions_for(user, survey: Survey) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(effective_role(user, survey), frozenset())


def permissions_for_org(user, organization: Organization) -> frozenset[str]:
    """Capabilities that exist before any survey does: creating one, managing members."""
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    return ROLE_PERMISSIONS.get(org_role(user, organization.id), frozenset())


def visible_surveys(user, organization_id):
    """Surveys this user may see.

    Scope querysets with this rather than checking per view: list and detail
    share one filter, so a survey the user cannot list is a 404 on direct
    fetch rather than a 403 that would confirm the id exists.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Survey.objects.none()

    role = org_role(user, organization_id)
    base = Survey.objects.filter(organization_id=organization_id)

    if role in ORG_WIDE_ROLES:
        return base
    if role is None:
        # Not a member of the owning organization, so nothing here is
        # visible. Checked before the grant filter rather than relying on it:
        # a SurveyAccess row for a non-member would otherwise make the survey
        # visible while effective_role still refused every capability, and a
        # 403 in place of a 404 confirms the id exists.
        return Survey.objects.none()
    return base.filter(access__user=user)
