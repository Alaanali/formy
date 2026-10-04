/**
 * Client-side mirror of the backend's condition evaluator.
 *
 * Why duplicate it at all: the server returns resolved visibility with every
 * save, but waiting for a round trip before showing or hiding a field makes
 * the form feel broken. This evaluates locally for instant feedback and is
 * then reconciled with the server's payload after each autosave, which stays
 * authoritative.
 *
 * Every rule below matches `surveys/logic.py` deliberately. A parity test
 * feeds the same fixtures through both and asserts they agree, because a
 * divergence here is worse than having no local evaluator: the respondent
 * would answer a field the server considers hidden and have it discarded.
 */

import type {
  AnswerValue,
  Answers,
  FieldDefinition,
  Leaf,
  Operator,
  Option,
  Rule,
  SurveySchema,
} from "./types";

/** Distinct from null, which is a legitimate stored answer. */
type Comparable = AnswerValue | undefined;

const NON_ANSWERABLE = new Set(["display"]);

/**
 * Zero and false are answers. Empty string, empty array and null are not.
 * The obvious truthiness check would silently discard every zero.
 */
export function isAnswered(value: Comparable): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function toNumber(value: unknown): number | null {
  if (typeof value === "boolean") return null; // a boolean is not a number
  const n = typeof value === "number" ? value : Number(String(value));
  return Number.isFinite(n) ? n : null;
}

function toDate(value: unknown): number | null {
  const parsed = Date.parse(`${String(value)}T00:00:00Z`);
  return Number.isNaN(parsed) ? null : parsed;
}

function compare(
  op: Operator,
  fieldType: string | undefined,
  answer: Comparable,
  operand: unknown,
): boolean {
  if (op === "answered") return isAnswered(answer);

  // Any comparison against an absent value is false. Without this a stale
  // answer to a now-hidden field keeps downstream fields alive.
  if (!isAnswered(answer)) return false;

  if (op === "contains") {
    if (Array.isArray(answer)) return answer.includes(operand as string);
    return String(answer).toLowerCase().includes(String(operand).toLowerCase());
  }

  let left: number | string | boolean;
  let right: number | string | boolean;

  if (fieldType === "number") {
    const a = toNumber(answer);
    const b = toNumber(operand);
    if (a === null || b === null) return false;
    [left, right] = [a, b];
  } else if (fieldType === "date") {
    const a = toDate(answer);
    const b = toDate(operand);
    if (a === null || b === null) return false;
    [left, right] = [a, b];
  } else {
    left = answer as string;
    right = operand as string;
  }

  switch (op) {
    case "eq":
      return left === right;
    case "ne":
      return left !== right;
    case "gt":
      return left > right;
    case "gte":
      return left >= right;
    case "lt":
      return left < right;
    case "lte":
      return left <= right;
    default:
      return false;
  }
}

function evaluateLeaf(
  leaf: Leaf,
  schema: SurveySchema,
  answers: Answers,
  visible: Record<string, boolean>,
): boolean {
  if (!leaf || typeof leaf !== "object" || !leaf.field || !leaf.op) return false;

  // A reference to a field that is not visible reads as absent, regardless
  // of what is stored against it.
  // A reference to a field that is not visible reads as unanswered.
  const answer: Comparable = visible[leaf.field] ? answers[leaf.field] : undefined;
  return compare(leaf.op, schema.fields[leaf.field]?.type, answer, leaf.value);
}

export function evaluateRule(
  rule: Rule | undefined,
  schema: SurveySchema,
  answers: Answers,
  visible: Record<string, boolean>,
): boolean {
  if (rule === undefined || rule === null || rule === true) return true;
  if (rule === false) return false;
  if (typeof rule !== "object") return false;

  if ("all" in rule) {
    return rule.all.every((leaf) => evaluateLeaf(leaf, schema, answers, visible));
  }
  if ("any" in rule) {
    // An empty any-group is false: no condition was satisfied.
    return rule.any.some((leaf) => evaluateLeaf(leaf, schema, answers, visible));
  }
  // A bare leaf is accepted as a single-condition group.
  return evaluateLeaf(rule as unknown as Leaf, schema, answers, visible);
}

/**
 * Decide which fields the respondent sees, walking eval_order so a field is
 * never evaluated before the one it depends on.
 *
 * Visibility belongs to fields. A section carries no rule of its own and
 * renders while any of its fields is visible, so a conditional section is
 * expressed by gating its fields.
 */
export function resolveVisibility(
  schema: SurveySchema,
  answers: Answers,
): Record<string, boolean> {
  const visible: Record<string, boolean> = {};
  const order = schema.eval_order?.length ? schema.eval_order : Object.keys(schema.fields);

  for (const fieldId of order) {
    const field = schema.fields[fieldId];
    if (!field) continue;
    visible[fieldId] = evaluateRule(field.visible, schema, answers, visible);
  }
  return visible;
}

/**
 * A hidden field is never required. Otherwise a conditionally hidden
 * required field blocks submission forever, with an error pointing at
 * something the respondent cannot see.
 */
export function resolveRequired(
  schema: SurveySchema,
  answers: Answers,
  visible: Record<string, boolean>,
): Record<string, boolean> {
  const required: Record<string, boolean> = {};

  for (const [fieldId, field] of Object.entries(schema.fields)) {
    if (!visible[fieldId] || NON_ANSWERABLE.has(field.type)) {
      required[fieldId] = false;
    } else {
      required[fieldId] = evaluateRule(field.required ?? false, schema, answers, visible);
    }
  }
  return required;
}

/**
 * Filter a choice field's options. This is how an answer in one section
 * narrows the choices in another -- a separate mechanism from visibility,
 * reusing the same evaluator rather than overloading `visible`.
 */
export function visibleOptions(
  field: FieldDefinition,
  schema: SurveySchema,
  answers: Answers,
  visible: Record<string, boolean>,
): Option[] {
  return (field.options ?? []).filter((option) =>
    evaluateRule(option.when, schema, answers, visible),
  );
}

/** Sections render when at least one of their fields is visible. */
export function visibleSections(schema: SurveySchema, visible: Record<string, boolean>) {
  return [...schema.sections]
    .sort((a, b) => a.order - b.order)
    .filter((section) => section.fields.some((fieldId) => visible[fieldId]));
}

/** Fields the respondent still owes an answer for, within one section. */
export function missingRequired(
  sectionFieldIds: string[],
  answers: Answers,
  visible: Record<string, boolean>,
  required: Record<string, boolean>,
): string[] {
  return sectionFieldIds.filter(
    (fieldId) => visible[fieldId] && required[fieldId] && !isAnswered(answers[fieldId]),
  );
}

/** Drop answers to fields the logic now hides, mirroring what submit does. */
export function pruneHidden(answers: Answers, visible: Record<string, boolean>): Answers {
  const kept: Answers = {};
  for (const [fieldId, value] of Object.entries(answers)) {
    if (visible[fieldId]) kept[fieldId] = value;
  }
  return kept;
}
