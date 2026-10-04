from __future__ import annotations

import operator
import uuid
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    ValidationError,
    model_validator,
)


class Op(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    ANSWERED = "answered"


class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    DROPDOWN = "dropdown"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    BOOLEAN = "boolean"
    FILE = "file"
    DISPLAY = "display"  # static content: carries conditions, holds no answer


#: Which operators make sense for which field type. Enforced at publish, so a
#: nonsensical rule is a clear authoring error rather than a condition that
#: silently evaluates false forever.
ALLOWED_OPS: dict[str, frozenset[str]] = {
    FieldType.TEXT: frozenset({Op.EQ, Op.NE, Op.ANSWERED, Op.CONTAINS}),
    FieldType.TEXTAREA: frozenset({Op.EQ, Op.NE, Op.ANSWERED, Op.CONTAINS}),
    FieldType.NUMBER: frozenset({Op.EQ, Op.NE, Op.ANSWERED, Op.GT, Op.GTE, Op.LT, Op.LTE}),
    FieldType.DATE: frozenset({Op.EQ, Op.NE, Op.ANSWERED, Op.GT, Op.GTE, Op.LT, Op.LTE}),
    FieldType.DROPDOWN: frozenset({Op.EQ, Op.NE, Op.ANSWERED}),
    FieldType.RADIO: frozenset({Op.EQ, Op.NE, Op.ANSWERED}),
    FieldType.CHECKBOX: frozenset({Op.EQ, Op.NE, Op.ANSWERED, Op.CONTAINS}),
    FieldType.BOOLEAN: frozenset({Op.EQ, Op.NE, Op.ANSWERED}),
    FieldType.FILE: frozenset({Op.ANSWERED}),
    FieldType.DISPLAY: frozenset(),  # nothing can depend on static content
}

#: Field types that never hold an answer.
NON_ANSWERABLE = frozenset({FieldType.DISPLAY})


#: Unknown keys are ignored, not rejected: a published schema is frozen and
#: must still load years later, so a key this version does not know about
#: cannot be an error. The cost is that a misspelled "visibile" is silently
#: dropped. Rejecting unknown keys at publish, where the document is still
#: being authored, would catch that without making frozen schemas brittle.
#: frozen because a published document is immutable.
BASE = ConfigDict(extra="ignore", frozen=True)

CHOICE_TYPES = frozenset({FieldType.DROPDOWN, FieldType.RADIO, FieldType.CHECKBOX})

#: Operator -> comparison, once both sides are coerced.
COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    Op.EQ: operator.eq,
    Op.NE: operator.ne,
    Op.GT: operator.gt,
    Op.GTE: operator.ge,
    Op.LT: operator.lt,
    Op.LTE: operator.le,
}


def is_answered(value: Any) -> bool:
    """Zero and False are answers. Empty string, empty list and None are not."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list | dict):
        return len(value) > 0
    return True


def _coerce(field_type: str, value: Any) -> Any:
    """Bring a JSON value into something comparable for its declared type."""
    if field_type == FieldType.NUMBER:
        if isinstance(value, bool):
            raise TypeError("boolean is not a number")
        return Decimal(str(value))
    if field_type == FieldType.DATE:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    return value


def _contains(answer: Any, operand: Any) -> bool:
    """Array membership for a multi-choice answer, substring for text."""
    if isinstance(answer, list):
        return operand in answer
    return str(operand).casefold() in str(answer).casefold()


def _compare(op: str, field_type: str, answer: Any, operand: Any) -> bool:
    if op == Op.ANSWERED:
        return is_answered(answer)

    # Any comparison against an absent value is false. Without this rule a
    # stale answer to a now-hidden field keeps downstream fields visible --
    # the ghost-dependency bug.
    if not is_answered(answer):
        return False

    if op == Op.CONTAINS:
        return _contains(answer, operand)

    try:
        left = _coerce(field_type, answer)
        right = _coerce(field_type, operand)
    except ValueError, TypeError, InvalidOperation:
        # Malformed data cannot satisfy a condition. Publish catches the
        # authoring side; this keeps the runtime predictable.
        return False

    compare = COMPARISONS.get(op)
    return compare(left, right) if compare else False


def holds(rule: Rule | None, document: Document, answers: dict, visible: dict) -> bool:
    """Evaluate a rule. An absent rule means "no condition", which is true."""
    if rule is None or rule is True:
        return True
    if rule is False:
        return False
    return rule.holds(document, answers, visible)


class Condition(BaseModel):
    """One comparison, e.g. `age >= 18`."""

    model_config = BASE

    field: uuid.UUID
    op: Op
    #: Any, because the operand's type is decided by the *referenced* field,
    #: which this model cannot see.
    value: Any = None

    @property
    def conditions(self) -> list[Condition]:
        """Itself, so a bare condition and a group read the same way."""
        return [self]

    def holds(self, document: Document, answers: dict, visible: dict) -> bool:
        """This comparison, against the answers decided so far.

        A reference to a field that is not visible reads as absent, and any
        comparison against absent is false -- without that, a stale answer to
        a now-hidden field keeps downstream fields alive.
        """
        referenced = document.fields.get(self.field)
        if referenced is None:
            # Publish rejects a dangling reference, so this is only reachable
            # for a draft -- which should preview rather than raise.
            return False

        # A reference to a field that is not visible reads as unanswered,
        # whatever is stored against it.
        answer = answers.get(self.field) if visible.get(self.field, False) else None
        return _compare(self.op, referenced.type, answer, self.value)


def _not_a_group(value: Any) -> Any:
    """Groups hold conditions, so nesting is impossible by construction. This
    only makes the reason legible instead of reporting a shape mismatch."""
    if isinstance(value, dict) and ({"all", "any"} & value.keys()):
        raise ValueError("nested groups are not supported in v1")
    return value


Member = Annotated[Condition, BeforeValidator(_not_a_group)]


class AllOf(BaseModel):
    """Every condition must hold."""

    model_config = BASE
    all: list[Member] = Field(min_length=1)

    @property
    def conditions(self) -> list[Condition]:
        return self.all

    def holds(self, document: Document, answers: dict, visible: dict) -> bool:
        return all(c.holds(document, answers, visible) for c in self.all)


class AnyOf(BaseModel):
    """At least one condition must hold. Empty is refused: `any([])` is false,
    so it would hide the field forever with nothing to explain why."""

    model_config = BASE
    any: list[Member] = Field(min_length=1)

    @property
    def conditions(self) -> list[Condition]:
        return self.any

    def holds(self, document: Document, answers: dict, visible: dict) -> bool:
        return any(c.holds(document, answers, visible) for c in self.any)


def _rule_kind(value: Any) -> str | None:
    """Which of the four shapes this rule is.

    A callable discriminator rather than a plain union: a union tries every
    member and reports all their complaints, so one misspelled operator gave
    five errors whose clearest line was "Input should be a valid boolean".
    Naming the shape routes to exactly one member, so one mistake is one
    error.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, AllOf):
        return "all"
    if isinstance(value, AnyOf | Condition):
        return "any" if isinstance(value, AnyOf) else "condition"

    keys = value.keys() if isinstance(value, dict) else ()
    for kind in ("all", "any"):
        if kind in keys:
            return kind
    return "condition" if "field" in keys else None


#: A bare Condition is shorthand for a one-condition group. Flatness is a
#: property of the type rather than a check: groups contain Conditions.
Rule = Annotated[
    Annotated[bool, Tag("bool")]
    | Annotated[AllOf, Tag("all")]
    | Annotated[AnyOf, Tag("any")]
    | Annotated[Condition, Tag("condition")],
    Discriminator(_rule_kind),
]


class Option(BaseModel):
    """One choice. `when` gates it on an earlier answer, which is how an
    answer in one section filters another's options."""

    model_config = BASE

    value: str
    label: str | None = None
    when: Rule | None = None


class FieldDefinition(BaseModel):
    """One question."""

    model_config = BASE

    type: FieldType
    key: str | None = None
    label: str | None = None
    help: str | None = None
    visible: Rule | None = None
    required: Rule | None = None
    options: list[Option] = []
    #: Not Decimal: it serialises to a JSON string, rewriting a stored 100
    #: as "100".
    min: int | float | None = None
    max: int | float | None = None
    max_length: int | None = None
    #: Position within its section. Explicit because Section.content is a
    #: jsonb column and jsonb sorts object keys, so the order fields were
    #: written in does not survive a round trip. It only ever looked right
    #: because UUIDv7 is time-ordered, which made key order match creation
    #: order by accident -- and made reordering impossible.
    order: int = 0
    #: Encrypted at rest and never aggregated. Applies to file answers too.
    sensitive: bool = False

    @property
    def is_choice(self) -> bool:
        return self.type in CHOICE_TYPES

    @property
    def answerable(self) -> bool:
        return self.type not in NON_ANSWERABLE

    @property
    def allowed_ops(self) -> frozenset[str]:
        return ALLOWED_OPS.get(self.type, frozenset())

    def available_options(self, document: Document, answers: dict, visible: dict) -> list[Option]:
        """The options still choosable, given earlier answers."""
        return [o for o in self.options if holds(o.when, document, answers, visible)]

    @model_validator(mode="after")
    def _a_choice_field_can_be_chosen_from(self) -> Self:
        if not self.is_choice:
            return self
        if not self.options:
            raise ValueError("a choice field needs at least one option")
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("option values must be unique")
        return self


class Section(BaseModel):
    """A group of questions. Carries no rule: visibility belongs to fields, and
    a section renders while any of its fields is visible."""

    model_config = BASE

    key: str
    title: str
    order: int = 0
    fields: list[uuid.UUID] = []


class Document(BaseModel):
    """One survey version's schema. Immutable once published."""

    model_config = BASE

    sections: list[Section] = []
    fields: dict[uuid.UUID, FieldDefinition] = {}
    #: Filled in at publish by the topological sort.
    eval_order: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _no_field_in_two_sections(self) -> Self:
        """A respondent would be asked the same question twice, and the
        second answer would overwrite the first."""
        seen: set[uuid.UUID] = set()
        doubled: set[uuid.UUID] = set()
        for section in self.sections:
            for field_id in section.fields:
                (doubled if field_id in seen else seen).add(field_id)
        if doubled:
            listed = ", ".join(sorted(str(f) for f in doubled))
            raise ValueError(f"these fields appear in more than one section: {listed}")
        return self

    @property
    def order(self) -> list[uuid.UUID]:
        """eval_order once published, declaration order while a draft."""
        return self.eval_order or list(self.fields)

    def answerable_ids(self) -> list[uuid.UUID]:
        return [fid for fid in self.order if self.fields[fid].answerable]

    def visibility(self, answers: dict) -> dict[uuid.UUID, bool]:
        """Which fields this respondent sees.

        Visibility is a property of a field and nothing else; a conditional
        section is expressed by gating its fields. eval_order guarantees that
        every field a rule reads is already decided when the rule runs.
        """
        visible: dict[uuid.UUID, bool] = {}
        for field_id in self.order:
            visible[field_id] = holds(self.fields[field_id].visible, self, answers, visible)
        return visible

    def required(self, answers: dict, visible: dict) -> dict[uuid.UUID, bool]:
        """Which visible fields must be answered. A hidden field never is."""
        required: dict[uuid.UUID, bool] = {}
        for field_id, field in self.fields.items():
            if not visible.get(field_id, False) or not field.answerable:
                required[field_id] = False
            else:
                # An absent rule means NOT required -- the opposite of
                # visibility, where absent means visible. `None` is true to
                # holds(), so passing it through would make every unruled
                # field mandatory.
                required[field_id] = field.required is not None and holds(
                    field.required, self, answers, visible
                )
        return required

    def iter_rules(self) -> Iterator[tuple[str, Rule | None]]:
        """(where, rule) for every rule. `where` is only for error messages."""
        for field_id, field in self.fields.items():
            yield f"field {field_id} visible", field.visible
            yield f"field {field_id} required", field.required
            for i, option in enumerate(field.options):
                yield f"field {field_id} option[{i}]", option.when

    def to_stored(self) -> dict:
        """The form written to SurveyVersion.schema.

        mode="json" turns UUID keys into strings; exclude_defaults keeps an
        absent key absent. Together they make a parse-and-write round trip
        reproduce the stored column byte for byte.
        """
        return self.model_dump(mode="json", exclude_defaults=True)


_RULE = TypeAdapter(Rule | None)


def parse_rule(raw: Any) -> Rule | None:
    """One rule on its own, for a caller holding a rule rather than a
    document. None means "no condition" and is returned as-is."""
    try:
        return _RULE.validate_python(raw)
    except ValidationError as exc:
        raise SchemaValidationError([_render(error) for error in exc.errors()]) from exc


def conditions_of(rule: Rule | None) -> list[Condition]:
    """Every condition in a rule. A bool or absent rule has none."""
    return getattr(rule, "conditions", [])


class SchemaValidationError(Exception):
    """Raised with every problem found, not just the first."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def parse(raw: dict) -> Document:
    """A stored or assembled document, as a Document."""
    try:
        return Document.model_validate(raw)
    except ValidationError as exc:
        raise SchemaValidationError([_render(error) for error in exc.errors()]) from exc


def _render(error: dict) -> str:
    """One pydantic error as one sentence."""
    noise = {"all", "any", "AllOf", "AnyOf", "Condition", "bool", "function-before"}
    where = " ".join(str(part) for part in error["loc"] if str(part) not in noise)
    message = error["msg"].removeprefix("Value error, ")
    return f"{where}: {message}." if where else f"{message}."
