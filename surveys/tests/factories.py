import uuid

from surveys.document import FieldType


def fid() -> str:
    return str(uuid.uuid7())


def field(ftype=FieldType.TEXT, **extra) -> dict:
    definition = {"type": ftype, "label": extra.pop("label", "Question"), **extra}
    return definition


def choice(ftype=FieldType.DROPDOWN, values=("a", "b"), **extra) -> dict:
    return field(ftype, options=[{"value": v, "label": v.upper()} for v in values], **extra)


def document(fields: dict, sections=None) -> dict:
    """A minimal valid document: one section holding every field."""
    if sections is None:
        sections = [
            {
                "key": "s1",
                "title": "Section 1",
                "order": 1,
                "fields": list(fields),
            }
        ]
    for section in sections:
        # Titles matter to a builder and not to these tests, so a fixture
        # that only cares about field placement need not spell one out.
        section.setdefault("title", section["key"].upper())

    return {"sections": sections, "fields": fields, "eval_order": []}


def eq(field_id, value) -> dict:
    return {"all": [{"field": field_id, "op": "eq", "value": value}]}
