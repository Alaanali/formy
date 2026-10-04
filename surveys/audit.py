from auditlog.registry import auditlog

from accounts.models import Membership, Organization
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion


def register() -> None:
    auditlog.register(Organization)
    # Required rather than optional: SurveyAccess carries no granted_by
    # column, so this log is the only record of who granted whom access.
    auditlog.register(Membership)
    auditlog.register(SurveyAccess)
    auditlog.register(Survey)
    # The schema is excluded: a JSON diff of an entire survey document is
    # noise, and the version row is immutable once published anyway.
    auditlog.register(SurveyVersion, exclude_fields=["schema"])
    auditlog.register(Section)
