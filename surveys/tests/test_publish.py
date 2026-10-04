import pytest

from surveys import validators
from surveys.document import FieldType, SchemaValidationError, parse
from surveys.models import Section, SurveyVersion
from surveys.publish import assemble, derive_draft, publish, topological_order
from surveys.tests.factories import choice, document, eq, fid, field


def errors_for(raw) -> str:
    """Every problem with a raw document, from either half of validation.

    Parsing rejects a malformed document and validate() rejects an incoherent
    one. A test asserting on a message should not have to know which half
    objected, so this runs both and joins whatever came back.
    """
    try:
        document = parse(raw)
    except SchemaValidationError as exc:
        return " | ".join(exc.errors)
    return " | ".join(validators.problems(document))


# --- structural validation ---------------------------------------------------


def test_a_valid_document_has_no_errors():
    a = fid()
    assert validators.problems(parse(document({a: choice()}))) == []


def test_field_id_must_be_a_uuid():
    assert "valid UUID" in errors_for(document({"q_country": choice()}))


def test_unknown_field_type_is_rejected():
    problems = errors_for(document({fid(): {"type": "telepathy"}}))

    # The message should say which key is wrong and what is allowed, so the
    # author can fix it without reading the source.
    assert "type" in problems
    assert "'dropdown'" in problems


def test_choice_field_needs_options():
    assert "at least one option" in errors_for(document({fid(): {"type": FieldType.DROPDOWN}}))


def test_duplicate_option_values_are_rejected():
    bad = {"type": FieldType.DROPDOWN, "options": [{"value": "a"}, {"value": "a"}]}
    assert "option values must be unique" in errors_for(document({fid(): bad}))


def test_field_cannot_appear_in_two_sections():
    a = fid()
    doc = document(
        {a: choice()},
        sections=[
            {"key": "s1", "order": 1, "fields": [a]},
            {"key": "s2", "order": 2, "fields": [a]},
        ],
    )
    assert "appear in more than one section" in errors_for(doc)


def test_empty_survey_is_rejected():
    assert "no fields" in errors_for(document({}))


# --- rule validation ---------------------------------------------------------


def test_dangling_reference_is_rejected():
    a, ghost = fid(), fid()
    doc = document({a: field(FieldType.TEXT, visible=eq(ghost, "x"))})
    assert "references unknown field" in errors_for(doc)


def test_operator_must_suit_the_referenced_field_type():
    """`gt` on a dropdown is meaningless; rejecting it at publish turns a
    silently-always-false rule into a clear authoring error."""
    a, b = fid(), fid()
    doc = document(
        {
            a: choice(),
            b: field(FieldType.TEXT, visible={"all": [{"field": a, "op": "gt", "value": "a"}]}),
        }
    )
    assert "is not valid for a" in errors_for(doc)


def test_operand_type_must_match_the_field_type():
    """An operand that cannot be the field's type at all is refused.

    Note what is *not* refused: the string "30" against a number field is
    accepted, because both evaluators coerce it to 30 and agree. Only a
    value no coercion can rescue -- "abc" here -- is an authoring error.
    """
    a, b = fid(), fid()
    doc = document(
        {
            a: field(FieldType.NUMBER),
            b: field(FieldType.TEXT, visible={"all": [{"field": a, "op": "gt", "value": "abc"}]}),
        }
    )
    assert "is not a number" in errors_for(doc)


def test_boolean_is_not_accepted_as_a_number():
    a, b = fid(), fid()
    doc = document(
        {
            a: field(FieldType.NUMBER),
            b: field(FieldType.TEXT, visible={"all": [{"field": a, "op": "gt", "value": True}]}),
        }
    )
    assert "is a boolean, not a number" in errors_for(doc)


def test_operand_must_be_a_declared_option():
    a, b = fid(), fid()
    doc = document({a: choice(values=("sa", "eg")), b: field(FieldType.TEXT, visible=eq(a, "fr"))})
    assert "not one of the declared options" in errors_for(doc)


def test_answered_takes_no_value():
    a, b = fid(), fid()
    doc = document(
        {
            a: field(FieldType.TEXT),
            b: field(
                FieldType.TEXT, visible={"all": [{"field": a, "op": "answered", "value": "x"}]}
            ),
        }
    )
    assert "takes no value" in errors_for(doc)


def test_nested_groups_are_rejected_in_v1():
    a, b = fid(), fid()
    nested = {"all": [{"any": [{"field": a, "op": "eq", "value": "a"}]}]}
    doc = document({a: choice(), b: field(FieldType.TEXT, visible=nested)})
    assert "nested groups are not supported" in errors_for(doc)


def test_option_rules_are_validated_too():
    a, b = fid(), fid()
    city = choice(values=("riyadh",))
    city["options"][0]["when"] = eq(fid(), "sa")  # dangling
    doc = document({a: choice(), b: city})
    assert "references unknown field" in errors_for(doc)


def test_every_error_is_reported_not_just_the_first():
    doc = document({"not-a-uuid": {"type": "telepathy"}})
    assert len(errors_for(doc).split(" | ")) >= 2


# --- dependency order --------------------------------------------------------


def test_eval_order_follows_dependencies():
    a, b, c = fid(), fid(), fid()
    doc = document(
        {
            c: field(FieldType.TEXT, visible=eq(b, "x")),
            b: field(FieldType.TEXT, visible=eq(a, "x")),
            a: field(FieldType.TEXT),
        }
    )
    # Stringified to compare: the document is keyed by UUID internally while
    # a stored id -- which is what fid() mints -- is a string.
    assert [str(f) for f in topological_order(parse(doc))] == [a, b, c]


def test_cycles_are_rejected():
    a, b = fid(), fid()
    doc = document(
        {a: field(FieldType.TEXT, visible=eq(b, "x")), b: field(FieldType.TEXT, visible=eq(a, "x"))}
    )
    with pytest.raises(SchemaValidationError, match="cycle"):
        topological_order(parse(doc))


def test_order_is_stable_across_runs():
    fields = {fid(): field(FieldType.TEXT) for _ in range(8)}
    doc = document(fields)
    assert topological_order(parse(doc)) == topological_order(parse(doc))


# --- assembly and publish ----------------------------------------------------


@pytest.mark.django_db
def test_assemble_merges_sections_in_order(draft):
    a, b = fid(), fid()
    Section.objects.create(version=draft, key="s2", title="Two", order=2, content={b: choice()})
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={a: choice()})

    doc = assemble(draft)

    assert [section.key for section in doc.sections] == ["s1", "s2"]
    assert {str(f) for f in doc.fields} == {a, b}
    assert [str(f) for f in doc.sections[0].fields] == [a]


@pytest.mark.django_db
def test_publish_freezes_the_document(draft):
    a = fid()
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={a: choice()})

    published = publish(draft)

    assert published.status == SurveyVersion.Status.PUBLISHED
    assert published.published_at is not None
    assert published.schema["eval_order"] == [a]
    assert published.schema["fields"][a]["type"] == FieldType.DROPDOWN


@pytest.mark.django_db
def test_publishing_an_invalid_draft_changes_nothing(draft):
    Section.objects.create(
        version=draft, key="s1", title="One", order=1, content={"not-a-uuid": choice()}
    )

    with pytest.raises(SchemaValidationError, match="UUID"):
        publish(draft)

    draft.refresh_from_db()
    assert draft.status == SurveyVersion.Status.DRAFT
    assert draft.schema == {}


@pytest.mark.django_db
def test_a_version_can_only_be_published_once(draft):
    a = fid()
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={a: choice()})
    publish(draft)

    with pytest.raises(SchemaValidationError, match="already published"):
        publish(draft)


@pytest.mark.django_db
def test_derive_draft_preserves_field_ids(draft):
    """v2 keeps v1's field UUIDs, so analytics and exports align across
    versions without anyone re-typing an identifier."""
    a = fid()
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={a: choice()})
    v1 = publish(draft)

    v2 = derive_draft(v1)

    assert v2.version_number == 2
    assert v2.is_draft
    assert list(v2.sections.first().content) == [a]


@pytest.mark.django_db
def test_published_schema_survives_edits_to_the_draft_it_came_from(draft):
    """The reason the assembled document is stored rather than recomputed."""
    a = fid()
    Section.objects.create(version=draft, key="s1", title="One", order=1, content={a: choice()})
    v1 = publish(draft)
    original = v1.schema

    v2 = derive_draft(v1)
    section = v2.sections.first()
    section.content = {fid(): choice()}
    section.save()

    v1.refresh_from_db()
    assert v1.schema == original


def test_a_field_cannot_gate_itself():
    """A self-referencing visibility rule publishes and is then always false.

    resolve_visibility builds its map field by field, so a rule that reads
    its own field reads an undecided entry -- absent, and absent compares
    false. The field is invisible whatever the respondent does, and
    _dependencies excludes self-edges so the cycle check never sees it.
    """
    a = fid()
    doc = document({a: field(FieldType.TEXT, visible={"all": [{"field": a, "op": "answered"}]})})

    assert "cannot depend on its own visibility" in errors_for(doc)


def test_a_required_rule_may_reference_its_own_field():
    """Unlike visibility, required() runs with the visibility map complete,
    so reading its own field is well defined."""
    a = fid()
    doc = document({a: field(FieldType.TEXT, required={"all": [{"field": a, "op": "answered"}]})})

    assert validators.problems(parse(doc)) == []


@pytest.mark.django_db
def test_field_order_follows_the_author_not_the_uuid(draft):
    """Section.content is jsonb, and jsonb sorts object keys. Field order was
    therefore whatever the ids happened to sort to -- which only looked right
    because UUIDv7 is time-ordered, so creation order matched by accident.
    An explicit `order` is what makes reordering possible at all.
    """
    first, second, third = fid(), fid(), fid()
    Section.objects.create(
        version=draft,
        key="s1",
        title="One",
        order=1,
        content={
            first: field(FieldType.TEXT, label="A", order=2),
            second: field(FieldType.TEXT, label="B", order=0),
            third: field(FieldType.TEXT, label="C", order=1),
        },
    )

    document = assemble(draft)

    assert [str(f) for f in document.sections[0].fields] == [second, third, first]


@pytest.mark.django_db
def test_published_order_survives_the_jsonb_round_trip(draft):
    """The rendering order lives in sections[].fields, a JSON *array*, which
    jsonb does preserve -- unlike the object keys it is built from."""
    a, b = fid(), fid()
    Section.objects.create(
        version=draft,
        key="s1",
        title="One",
        order=1,
        content={
            a: field(FieldType.TEXT, label="A", order=5),
            b: field(FieldType.TEXT, label="B", order=1),
        },
    )

    version = publish(draft)
    version.refresh_from_db()

    assert version.schema["sections"][0]["fields"] == [b, a]
