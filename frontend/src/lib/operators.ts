/**
 * Which operators the backend accepts for which field type.
 *
 * Mirrors ALLOWED_OPS in `surveys/logic.py`. Kept in its own module so the
 * editor component exports only a component, and so the table is findable
 * when the backend's list changes.
 */

import type { Operator } from "./types";

const OPS_BY_TYPE: Record<string, Operator[]> = {
  text: ["eq", "ne", "answered", "contains"],
  textarea: ["eq", "ne", "answered", "contains"],
  number: ["eq", "ne", "answered", "gt", "gte", "lt", "lte"],
  date: ["eq", "ne", "answered", "gt", "gte", "lt", "lte"],
  dropdown: ["eq", "ne", "answered"],
  radio: ["eq", "ne", "answered"],
  checkbox: ["eq", "ne", "answered", "contains"],
  boolean: ["eq", "ne", "answered"],
  file: ["answered"],
  // Nothing can depend on static content, since it holds no answer.
  display: [],
};

export const OP_LABEL: Record<Operator, string> = {
  eq: "is",
  ne: "is not",
  gt: "is more than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  contains: "contains",
  answered: "is answered",
};

export function allowedOps(type: string | undefined): Operator[] {
  return OPS_BY_TYPE[type ?? ""] ?? [];
}
