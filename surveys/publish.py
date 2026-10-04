from __future__ import annotations

from collections import deque
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from surveys import validators
from surveys.cache import warm
from surveys.document import Document, SchemaValidationError, conditions_of, parse
from surveys.models import Section, SurveyVersion

# --- assembly ----------------------------------------------------------------


def assemble(version: SurveyVersion) -> Document:
    """Merge a draft's Section rows into one parsed document."""
    sections: list[dict] = []
    fields: dict[str, Any] = {}

    for section in version.sections.all().order_by("order", "key"):
        content = section.content or {}
        # Sorted by the field's own `order`, because jsonb gave the keys back
        # in its canonical order rather than the author's. The id breaks ties
        # so the result is stable across publishes.
        ordered = sorted(content.items(), key=lambda item: (item[1].get("order", 0), item[0]))
        fields.update(dict(ordered))
        sections.append(
            {
                "key": section.key,
                "title": section.title,
                "order": section.order,
                "fields": [field_id for field_id, _ in ordered],
            }
        )

    return parse({"sections": sections, "fields": fields, "eval_order": []})


# --- dependency order --------------------------------------------------------


def _dependencies(document: Document) -> dict[UUID, set[UUID]]:
    """field -> the fields its own rules read."""
    return {
        field_id: {
            condition.field
            for rule in (field.visible, field.required, *(o.when for o in field.options))
            for condition in conditions_of(rule)
            if condition.field in document.fields and condition.field != field_id
        }
        for field_id, field in document.fields.items()
    }


def topological_order(document: Document) -> list[UUID]:
    """Kahn's algorithm: one pass gives both the evaluation order and the
    cycle check, so the expensive work happens once at publish rather than
    once per request.

    Ties are broken by declared position, so the order is stable across
    publishes of the same document.
    """
    deps = _dependencies(document)
    position = {field_id: i for i, field_id in enumerate(document.fields)}

    dependents: dict[UUID, list[UUID]] = {field_id: [] for field_id in deps}
    indegree = {field_id: len(refs) for field_id, refs in deps.items()}
    for field_id, refs in deps.items():
        for ref in refs:
            dependents[ref].append(field_id)

    ready = deque(sorted((f for f, d in indegree.items() if d == 0), key=position.get))
    order: list[UUID] = []

    while ready:
        field_id = ready.popleft()
        order.append(field_id)
        newly_ready = []
        for dependent in dependents[field_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly_ready.append(dependent)
        for dependent in sorted(newly_ready, key=position.get):
            ready.append(dependent)

    if len(order) != len(deps):
        cyclic = sorted(str(f) for f in set(deps) - set(order))
        raise SchemaValidationError(
            [f"Conditional logic contains a cycle involving: {', '.join(cyclic)}."]
        )

    return order


# --- publish -----------------------------------------------------------------


@transaction.atomic
def publish(version: SurveyVersion, *, published_by=None) -> SurveyVersion:
    """Assemble, validate, order and freeze."""
    if not version.is_draft:
        raise SchemaValidationError([f"Version {version.id} is already {version.status}."])

    document = assemble(version)

    if problems := validators.problems(document):
        raise SchemaValidationError(problems)

    ordered = document.model_copy(update={"eval_order": topological_order(document)})

    version.schema = ordered.to_stored()
    version.status = SurveyVersion.Status.PUBLISHED
    version.published_at = timezone.now()
    version.save(update_fields=["schema", "status", "published_at"])

    # Warm immediately so a launch burst does not stampede the database.
    transaction.on_commit(lambda: warm(version))
    return version


def derive_draft(version: SurveyVersion, *, created_by=None) -> SurveyVersion:
    """Start the next version from an existing one."""
    draft = SurveyVersion.objects.create_draft(version.survey, created_by=created_by)
    Section.objects.bulk_create(
        [
            Section(
                version=draft,
                key=section.key,
                title=section.title,
                order=section.order,
                content=section.content,
            )
            for section in version.sections.all()
        ]
    )
    return draft
