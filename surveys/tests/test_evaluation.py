from uuid import UUID

import pytest

from surveys.document import (
    CHOICE_TYPES,
    FieldType,
    Op,
    SchemaValidationError,
    holds,
    is_answered,
    parse,
    parse_rule,
)

# Real UUIDs rather than strings: the document is keyed by UUID, so the tests
# speak the same types the evaluator does.
COUNTRY = UUID("0199c3f2-1a40-7c31-9e55-000000000001")
AGE = UUID("0199c3f2-1a40-7c31-9e55-000000000002")
CITY = UUID("0199c3f2-1a40-7c31-9e55-000000000003")
DISTRICT = UUID("0199c3f2-1a40-7c31-9e55-000000000004")


def build(fields: dict, sections: list | None = None, order: list | None = None):
    """A parsed document.

    Choice fields are given options when a test did not set any: a choice
    field with nothing to choose from is not a valid document, and these
    tests are about conditions rather than about options.
    """
    for definition in fields.values():
        if definition.get("type") in CHOICE_TYPES and "options" not in definition:
            definition["options"] = [{"value": "sa"}, {"value": "eg"}]

    sections = sections or [{"key": "s1", "order": 1, "fields": list(fields)}]
    for section in sections:
        section.setdefault("title", section["key"].upper())

    return parse({"fields": fields, "sections": sections, "eval_order": order or list(fields)})


# --- is_answered -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ([], False),
        ({}, False),
        (0, True),  # zero is a real answer
        (False, True),  # so is "no"
        ("no", True),
        ([1], True),
    ],
)
def test_is_answered(value, expected):
    assert is_answered(value) is expected


# --- operators ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ftype", "answer", "op", "operand", "expected"),
    [
        (FieldType.DROPDOWN, "sa", Op.EQ, "sa", True),
        (FieldType.DROPDOWN, "sa", Op.EQ, "eg", False),
        (FieldType.DROPDOWN, "sa", Op.NE, "eg", True),
        (FieldType.NUMBER, 18, Op.GTE, 18, True),
        (FieldType.NUMBER, 17, Op.GTE, 18, False),
        (FieldType.NUMBER, 17.5, Op.GT, 17, True),
        (FieldType.NUMBER, "20", Op.GT, 18, True),  # JSON strings coerce
        (FieldType.NUMBER, 5, Op.LT, 10, True),
        (FieldType.NUMBER, 10, Op.LTE, 10, True),
        (FieldType.DATE, "2026-06-01", Op.GT, "2026-01-01", True),
        (FieldType.DATE, "2025-06-01", Op.GT, "2026-01-01", False),
        (FieldType.TEXT, "Hello World", Op.CONTAINS, "world", True),  # case-insensitive
        (FieldType.TEXT, "Hello", Op.CONTAINS, "xyz", False),
        (FieldType.CHECKBOX, ["a", "c"], Op.CONTAINS, "c", True),
        (FieldType.CHECKBOX, ["a", "c"], Op.CONTAINS, "b", False),
        (FieldType.TEXT, "anything", Op.ANSWERED, None, True),
        (FieldType.TEXT, "", Op.ANSWERED, None, False),
        (FieldType.NUMBER, 0, Op.ANSWERED, None, True),
    ],
)
def test_operators(ftype, answer, op, operand, expected):
    schema = build({COUNTRY: {"type": ftype}})
    rule = {"all": [{"field": COUNTRY, "op": op, "value": operand}]}

    assert holds(parse_rule(rule), schema, {COUNTRY: answer}, {COUNTRY: True}) is expected


def test_malformed_answer_cannot_satisfy_a_condition():
    """Garbage in a numeric field must not raise, and must not pass."""
    schema = build({AGE: {"type": FieldType.NUMBER}})
    rule = {"all": [{"field": AGE, "op": Op.GT, "value": 18}]}

    assert holds(parse_rule(rule), schema, {AGE: "not-a-number"}, {AGE: True}) is False


# --- groups ------------------------------------------------------------------


def test_all_requires_every_leaf():
    schema = build({COUNTRY: {"type": FieldType.DROPDOWN}, AGE: {"type": FieldType.NUMBER}})
    rule = {
        "all": [
            {"field": COUNTRY, "op": Op.EQ, "value": "sa"},
            {"field": AGE, "op": Op.GTE, "value": 18},
        ]
    }
    seen = {COUNTRY: True, AGE: True}

    assert holds(parse_rule(rule), schema, {COUNTRY: "sa", AGE: 20}, seen) is True
    assert holds(parse_rule(rule), schema, {COUNTRY: "sa", AGE: 16}, seen) is False


def test_any_requires_one_leaf():
    schema = build({COUNTRY: {"type": FieldType.DROPDOWN}, AGE: {"type": FieldType.NUMBER}})
    rule = {
        "any": [
            {"field": COUNTRY, "op": Op.EQ, "value": "sa"},
            {"field": AGE, "op": Op.GTE, "value": 65},
        ]
    }
    seen = {COUNTRY: True, AGE: True}

    assert holds(parse_rule(rule), schema, {COUNTRY: "eg", AGE: 70}, seen) is True
    assert holds(parse_rule(rule), schema, {COUNTRY: "eg", AGE: 30}, seen) is False


@pytest.mark.parametrize(("rule", "expected"), [(True, True), (False, False), (None, True)])
def test_boolean_rules_are_the_degenerate_condition(rule, expected):
    assert holds(parse_rule(rule), build({}), {}, {}) is expected


def test_an_empty_group_is_refused_at_parse():
    """Previously an empty `all` was vacuously true and an empty `any`
    silently false forever. Neither is anything an author meant to write, so
    the models reject both rather than guessing which was intended."""
    for empty in ({"all": []}, {"any": []}):
        with pytest.raises(SchemaValidationError, match="at least 1 item"):
            parse_rule(empty)


# --- the absent-value rule ---------------------------------------------------


def test_comparison_against_an_unanswered_field_is_false():
    schema = build({COUNTRY: {"type": FieldType.DROPDOWN}})
    rule = {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]}

    assert holds(parse_rule(rule), schema, {}, {COUNTRY: True}) is False


def test_reference_to_a_hidden_field_reads_as_absent():
    """Even with a stored answer, a hidden field contributes nothing."""
    schema = build({COUNTRY: {"type": FieldType.DROPDOWN}})
    rule = {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]}

    assert holds(parse_rule(rule), schema, {COUNTRY: "sa"}, {COUNTRY: False}) is False


def test_ne_against_an_absent_value_is_also_false():
    """Absent is not 'a different value' -- it is no value. Returning True
    here would make hidden fields silently satisfy negative conditions."""
    schema = build({COUNTRY: {"type": FieldType.DROPDOWN}})
    rule = {"all": [{"field": COUNTRY, "op": Op.NE, "value": "sa"}]}

    assert holds(parse_rule(rule), schema, {}, {COUNTRY: True}) is False


# --- cascades and the ghost-dependency bug -----------------------------------


def ghost_schema():
    return build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {
                "type": FieldType.DROPDOWN,
                "visible": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]},
            },
            DISTRICT: {
                "type": FieldType.TEXT,
                "visible": {"all": [{"field": CITY, "op": Op.EQ, "value": "riyadh"}]},
            },
        },
        order=[COUNTRY, CITY, DISTRICT],
    )


def test_cascade_reveals_dependent_fields():
    visible = ghost_schema().visibility({COUNTRY: "sa", CITY: "riyadh"})

    assert visible == {COUNTRY: True, CITY: True, DISTRICT: True}


def test_hiding_a_field_hides_everything_downstream():
    """The ghost-dependency case: the respondent picked Saudi Arabia, chose
    Riyadh, then changed the country. The stale Riyadh answer must not keep
    the district field alive."""
    visible = ghost_schema().visibility({COUNTRY: "eg", CITY: "riyadh"})

    assert visible == {COUNTRY: True, CITY: False, DISTRICT: False}


def test_cross_section_dependency():
    """A response in section 1 controls a field in section 2."""
    schema = build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {
                "type": FieldType.DROPDOWN,
                "visible": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]},
            },
        },
        sections=[
            {"key": "s1", "order": 1, "fields": [COUNTRY]},
            {"key": "s2", "order": 2, "fields": [CITY]},
        ],
        order=[COUNTRY, CITY],
    )

    assert schema.visibility({COUNTRY: "sa"})[CITY] is True
    assert schema.visibility({COUNTRY: "eg"})[CITY] is False


# --- sections ----------------------------------------------------------------


def two_sections(city_visible):
    """Two sections, with the second section's only field conditional.

    Sections carry no rule of their own, so this is how a whole section is
    made conditional: gate its fields.
    """
    return build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {"type": FieldType.DROPDOWN, "visible": city_visible},
        },
        sections=[
            {"key": "s1", "order": 1, "fields": [COUNTRY]},
            {"key": "s2", "order": 2, "fields": [CITY]},
        ],
        order=[COUNTRY, CITY],
    )


def test_a_section_is_conditional_through_its_fields():
    """What used to be a section rule. One rule on the field produces the
    same outcome, without two rules to reconcile."""
    gated = {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]}

    assert two_sections(gated).visibility({COUNTRY: "sa"})[CITY] is True
    assert two_sections(gated).visibility({COUNTRY: "eg"})[CITY] is False


def test_hidden_field_is_never_required():
    """Otherwise a hidden required field blocks submission forever, with an
    error pointing at something the respondent cannot see."""
    schema = build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {
                "type": FieldType.DROPDOWN,
                "required": True,
                "visible": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]},
            },
        },
        order=[COUNTRY, CITY],
    )
    answers = {COUNTRY: "eg"}
    visible = schema.visibility(answers)

    assert visible[CITY] is False
    assert schema.required(answers, visible)[CITY] is False


def test_conditionally_required_field():
    schema = build(
        {
            AGE: {"type": FieldType.NUMBER},
            CITY: {
                "type": FieldType.DROPDOWN,
                "required": {"any": [{"field": AGE, "op": Op.GTE, "value": 21}]},
            },
        },
        order=[AGE, CITY],
    )

    for age, expected in ((25, True), (18, False)):
        answers = {AGE: age}
        visible = schema.visibility(answers)
        assert schema.required(answers, visible)[CITY] is expected


def test_display_fields_are_never_required():
    notice = UUID("0199c3f2-1a40-7c31-9e55-00000000000f")
    schema = build({notice: {"type": FieldType.DISPLAY, "required": True}})
    visible = schema.visibility({})

    assert schema.required({}, visible)[notice] is False


# --- option filtering --------------------------------------------------------


def test_options_are_filtered_by_an_earlier_answer():
    """Field dependencies across sections: the answer to one field changes
    the options available on another. A separate mechanism from visibility,
    reusing the same evaluator."""
    schema = build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {
                "type": FieldType.DROPDOWN,
                "options": [
                    {
                        "value": "riyadh",
                        "when": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]},
                    },
                    {
                        "value": "cairo",
                        "when": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "eg"}]},
                    },
                    {"value": "other"},  # no rule: always offered
                ],
            },
        }
    )
    city = schema.fields[CITY]
    seen = {COUNTRY: True, CITY: True}

    sa = city.available_options(schema, {COUNTRY: "sa"}, seen)
    assert [o.value for o in sa] == ["riyadh", "other"]

    eg = city.available_options(schema, {COUNTRY: "eg"}, seen)
    assert [o.value for o in eg] == ["cairo", "other"]


def test_options_of_a_field_whose_dependency_is_hidden():
    schema = build(
        {
            COUNTRY: {"type": FieldType.DROPDOWN},
            CITY: {
                "type": FieldType.DROPDOWN,
                "options": [
                    {
                        "value": "riyadh",
                        "when": {"all": [{"field": COUNTRY, "op": Op.EQ, "value": "sa"}]},
                    }
                ],
            },
        }
    )

    assert schema.fields[CITY].available_options(schema, {COUNTRY: "sa"}, {COUNTRY: False}) == []
