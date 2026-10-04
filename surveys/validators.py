from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from surveys.document import (
    Condition,
    Document,
    FieldDefinition,
    FieldType,
    Op,
    conditions_of,
)


def _number_problem(value: Any) -> str | None:
    # Before Decimal: bool subclasses int, so Decimal(str(True)) would be a
    # clean parse of the wrong thing.
    if isinstance(value, bool):
        return "is a boolean, not a number"
    try:
        Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return "is not a number"
    return None


def _date_problem(value: Any) -> str | None:
    try:
        date.fromisoformat(str(value))
    except ValueError, TypeError:
        return "is not an ISO date"
    return None


#: What a literal must look like, per field type. Types absent from it have
#: no operand to check: ALLOWED_OPS limits file and display to `answered`.
OPERAND_CHECKS = {
    FieldType.NUMBER: _number_problem,
    FieldType.DATE: _date_problem,
    FieldType.BOOLEAN: lambda v: None if isinstance(v, bool) else "is not a boolean",
    FieldType.TEXT: lambda v: None if isinstance(v, str) else "is not a string",
    FieldType.TEXTAREA: lambda v: None if isinstance(v, str) else "is not a string",
}


def operand_problem(field: FieldDefinition, op: str, value: Any) -> str | None:
    """Whether a literal can legally be compared against this field."""
    if op == Op.ANSWERED:
        return None if value is None else "'answered' takes no value"

    # Against the field's own options rather than against a type, which is
    # why choice fields are not in OPERAND_CHECKS.
    if field.is_choice:
        declared = {option.value for option in field.options}
        if declared and value not in declared:
            return f"{value!r} is not one of the declared options"
        return None

    check = OPERAND_CHECKS.get(field.type)
    problem = check(value) if check else None
    return f"{value!r} {problem}" if problem else None


def condition_problem(condition: Condition, document: Document) -> str | None:
    """What is wrong with one condition, or None."""
    referenced = document.fields.get(condition.field)
    if referenced is None:
        return f"references unknown field {condition.field}."

    if condition.op not in referenced.allowed_ops:
        allowed = sorted(referenced.allowed_ops)
        return (
            f"operator {condition.op!r} is not valid for a {referenced.type!r} field ({allowed})."
        )

    problem = operand_problem(referenced, condition.op, condition.value)
    return f"{problem}." if problem else None


def _self_gating_fields(document: Document) -> list[str]:
    """A visibility rule that reads its own field.

    visibility() decides fields one at a time, so such a rule reads an entry
    that is not decided yet -- absent, and absent compares false. The field
    is then invisible whatever the respondent does. The cycle check cannot
    see it either, because the dependency graph excludes self-edges.

    `required` and an option's `when` are fine: both run with the visibility
    map already complete.
    """
    return [
        f"field {field_id} visible: a field cannot depend on its own visibility."
        for field_id, field in document.fields.items()
        for condition in conditions_of(field.visible)
        if condition.field == field_id
    ]


def problems(document: Document) -> list[str]:
    """Every reason this document could not be published.

    Separate from parsing on purpose. A published schema is frozen and must
    keep loading for as long as its answers are kept, so parsing only ever
    asks "is this a document". Whether it is one we would publish *today* is
    this module's question -- otherwise a rule that is no longer allowed
    would make an old survey unreadable.

    All the problems, not the first: fixing a survey one error per publish
    attempt is a miserable loop.
    """
    if not document.fields:
        return ["Survey has no fields."]

    return _self_gating_fields(document) + [
        f"{where}: {problem}"
        for where, rule in document.iter_rules()
        for condition in conditions_of(rule)
        if (problem := condition_problem(condition, document))
    ]
