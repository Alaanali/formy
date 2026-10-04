from __future__ import annotations

from auditlog.models import LogEntry


class Action:
    """Namespaced values for the `event` key in additional_data. LogEntry's
    own action column only distinguishes create/update/delete/access."""

    PII_ACCESS = "pii.access"
    SUBMISSION_READ = "submission.read"
    EXPORT_CREATE = "export.create"


def log_access(user, event: str, instance, **context) -> LogEntry | None:
    """Record that someone read something."""
    if instance is None or instance.pk is None:
        return None

    return LogEntry.objects.log_create(
        instance,
        force_log=True,
        action=LogEntry.Action.ACCESS,
        actor=user if getattr(user, "is_authenticated", False) else None,
        additional_data={"event": event, **context},
    )
