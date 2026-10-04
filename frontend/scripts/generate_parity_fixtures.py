"""Regenerate the conditional-logic parity fixtures from the REAL backend.

The frontend mirrors the backend's rule evaluator in TypeScript so the form
responds instantly. The two must agree exactly: if they diverge, a respondent
answers a field the server considers hidden and the answer is discarded.

These fixtures record what Python actually decides, so the TypeScript test
asserts against the backend's behaviour rather than a second guess at it.
From the repository root:

    pnpm --dir frontend fixtures
"""

import json
import os
import sys
from pathlib import Path

# frontend/scripts/x.py -> frontend -> repo root
BACKEND = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent.parent / "src/test/parity-fixtures.json"

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "formy.settings.test")

import django  # noqa: E402

django.setup()

from surveys.document import parse  # noqa: E402

COUNTRY = "0199c3f2-1a40-7c31-9e55-000000000001"
AGE = "0199c3f2-1a40-7c31-9e55-000000000002"
CITY = "0199c3f2-1a40-7c31-9e55-000000000003"
DISTRICT = "0199c3f2-1a40-7c31-9e55-000000000004"
NOTE = "0199c3f2-1a40-7c31-9e55-000000000005"
ATTACHMENT = "0199c3f2-1a40-7c31-9e55-000000000006"

SCHEMA = {
    "fields": {
        COUNTRY: {
            "type": "dropdown",
            "key": "country",
            "label": "Country",
            "required": True,
            "options": [
                {"value": "sa", "label": "Saudi Arabia"},
                {"value": "eg", "label": "Egypt"},
            ],
        },
        AGE: {"type": "number", "key": "age", "label": "Age", "min": 0, "max": 120},
        CITY: {
            "type": "dropdown",
            "key": "city",
            "label": "City",
            # Cross-section: depends on an answer in the previous section.
            # Its section holds only conditional fields, so the section
            # itself disappears along with them.
            "visible": {"all": [{"field": COUNTRY, "op": "eq", "value": "sa"}]},
            # Conditionally required, which is where "hidden implies not
            # required" has to hold on both sides.
            "required": {"any": [{"field": AGE, "op": "gte", "value": 21}]},
            "options": [
                {
                    "value": "riyadh",
                    "label": "Riyadh",
                    "when": {"all": [{"field": COUNTRY, "op": "eq", "value": "sa"}]},
                },
                {
                    "value": "cairo",
                    "label": "Cairo",
                    "when": {"all": [{"field": COUNTRY, "op": "eq", "value": "eg"}]},
                },
                {"value": "other", "label": "Somewhere else"},
            ],
        },
        DISTRICT: {
            "type": "text",
            "key": "district",
            "label": "District",
            # Two hops from country, so the cascade is exercised.
            "visible": {"all": [{"field": CITY, "op": "eq", "value": "riyadh"}]},
        },
        NOTE: {"type": "display", "key": "note", "label": "Thanks for your time."},
        # A file field, so the respondent tests have one to upload against
        # and `answered` on a file type is covered by the parity check.
        ATTACHMENT: {"type": "file", "key": "attachment", "label": "Attachment"},
    },
    "sections": [
        {"key": "s1", "title": "About you", "order": 1, "fields": [COUNTRY, AGE, ATTACHMENT]},
        {"key": "s2", "title": "Where you are", "order": 2, "fields": [CITY, DISTRICT]},
        {"key": "s3", "title": "Thanks", "order": 3, "fields": [NOTE]},
    ],
    "eval_order": [COUNTRY, AGE, CITY, DISTRICT, NOTE, ATTACHMENT],
}

CASES = [
    {"name": "nothing answered", "answers": {}},
    {"name": "country sa", "answers": {COUNTRY: "sa"}},
    {"name": "country eg", "answers": {COUNTRY: "eg"}},
    {"name": "sa and adult", "answers": {COUNTRY: "sa", AGE: 30}},
    {"name": "sa and minor", "answers": {COUNTRY: "sa", AGE: 18}},
    {"name": "sa riyadh", "answers": {COUNTRY: "sa", AGE: 30, CITY: "riyadh"}},
    {"name": "sa other city", "answers": {COUNTRY: "sa", AGE: 30, CITY: "other"}},
    # The ghost-dependency case: a stale city answer must not keep the
    # district question alive after the country changes.
    {"name": "stale city after switching country", "answers": {COUNTRY: "eg", CITY: "riyadh"}},
    # Zero is a real answer; naive truthiness would discard it.
    {"name": "age zero is an answer", "answers": {COUNTRY: "sa", AGE: 0}},
    {"name": "age boundary 21", "answers": {COUNTRY: "sa", AGE: 21}},
    {"name": "empty string is not an answer", "answers": {COUNTRY: ""}},
]


def main() -> None:
    import uuid

    document = parse(SCHEMA)
    cases = []

    def by_id(mapping):
        return {str(key): value for key, value in mapping.items()}

    for case in CASES:
        # The document is keyed by UUID; the fixture file -- and the
        # TypeScript evaluator that reads it -- speaks strings.
        answers = {uuid.UUID(k): v for k, v in case["answers"].items()}
        visible = document.visibility(answers)
        required = document.required(answers, visible)
        options = {
            str(field_id): [o.value for o in field.available_options(document, answers, visible)]
            for field_id, field in document.fields.items()
            if field.options
        }
        cases.append(
            {
                **case,
                "visible": by_id(visible),
                "required": by_id(required),
                "options": options,
            }
        )

    OUT.write_text(json.dumps({"schema": SCHEMA, "cases": cases}, indent=2) + "\n")
    print(f"Wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
