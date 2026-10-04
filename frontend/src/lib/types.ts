/**
 * Shapes mirroring the backend API.
 *
 * Hand-written rather than generated from the OpenAPI document: the schema
 * document is deliberately loose (`fields` is a map of arbitrary field
 * definitions), so a generator would produce `Record<string, unknown>` for
 * the part that matters most. These types encode what the backend actually
 * guarantees.
 */

export type FieldType =
  | "text"
  | "textarea"
  | "number"
  | "date"
  | "dropdown"
  | "radio"
  | "checkbox"
  | "boolean"
  | "file"
  | "display";

export type Operator =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "contains"
  | "answered";

export interface Leaf {
  field: string;
  op: Operator;
  value?: unknown;
}

/** v1 is flat: a group holds leaves, never other groups. */
export type Rule = boolean | { all: Leaf[] } | { any: Leaf[] } | null;

export interface Option {
  value: string;
  label?: string;
  /** Option-level condition: how an earlier answer filters this choice. */
  when?: Rule;
}

export interface FieldDefinition {
  type: FieldType;
  key?: string;
  label?: string;
  help?: string;
  required?: Rule;
  visible?: Rule;
  options?: Option[];
  min?: number;
  max?: number;
  max_length?: number;
  /** Position within the section. Explicit because the server stores
   *  `content` in a jsonb column, which sorts object keys. */
  order?: number;
  /** Encrypted at rest; never aggregated, never echoed back to a respondent. */
  sensitive?: boolean;
}

export interface SchemaSection {
  key: string;
  title: string;
  order: number;
  fields: string[];
}

export interface SurveySchema {
  sections: SchemaSection[];
  fields: Record<string, FieldDefinition>;
  /** Topological order computed at publish; the runtime evaluates in it. */
  eval_order: string[];
}

export type AnswerValue = string | number | boolean | string[] | null;
export type Answers = Record<string, AnswerValue>;

// --- auth -------------------------------------------------------------------

export interface TokenResponse {
  token: string;
  user_id: string;
  username: string;
}

// --- tenancy ----------------------------------------------------------------

export type OrgRole = "owner" | "admin" | "member";
export type SurveyRole = "editor" | "analyst" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: OrgRole | null;
  created_at: string;
}

export interface Survey {
  id: string;
  organization: string;
  name: string;
  slug: string;
  created_at: string;
  archived_at: string | null;
  my_role: OrgRole | SurveyRole | null;
  published_version: number | null;
}

export type VersionStatus = "draft" | "published" | "archived";

export interface SurveyVersion {
  id: string;
  survey: string;
  version_number: number;
  status: VersionStatus;
  created_at: string;
  published_at: string | null;
}

export interface SurveyVersionWithSchema extends SurveyVersion {
  schema: SurveySchema;
}

export interface Section {
  id: string;
  version: string;
  key: string;
  title: string;
  order: number;
  content: Record<string, FieldDefinition>;
}

// --- responses --------------------------------------------------------------

export type SubmissionStatus = "in_progress" | "completed" | "abandoned";

export interface StartedSubmission {
  id: string;
  status: SubmissionStatus;
  /** Returned once, at creation, and never echoed again. */
  resume_token: string;
  resume_expires_at: string | null;
  started_at: string;
}

export interface SubmissionState {
  id: string;
  survey: string;
  status: SubmissionStatus;
  started_at: string;
  last_activity_at: string;
  submitted_at: string | null;
  resume_expires_at: string | null;
  schema: SurveySchema;
  answers: Answers;
  /** Server-resolved. The client mirrors this but never overrides it. */
  visible: Record<string, boolean>;
  required: Record<string, boolean>;
  /** Option values still available per field, after filtering. */
  options: Record<string, string[]>;
}

export interface SubmissionFile {
  id: string;
  field_id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
}

export interface SubmissionSummary {
  id: string;
  status: SubmissionStatus;
  started_at: string;
  submitted_at: string | null;
  last_activity_at: string;
}

export interface SubmissionAnswers {
  submission: SubmissionSummary;
  /** A sensitive value the caller may not read appears as a redaction marker. */
  answers: Record<string, AnswerValue | { __redacted__: true }>;
}

// --- analytics --------------------------------------------------------------

export interface Funnel {
  started: number;
  completed: number;
  abandoned: number;
  completion_rate: number | null;
  average_duration_seconds: number | null;
}

export interface Bucket {
  bucket: string | null;
  count: number;
  share: number | null;
}

export interface FieldResult {
  field_id: string;
  key: string | null;
  label: string | null;
  type: FieldType;
  /** Respondents the logic actually showed this field to. */
  eligible: number;
  answered: number;
  /** answered / eligible, never answered / total submissions. */
  distribution_available: boolean;
  reason?: string;
  buckets?: Bucket[];
  numeric?: { sum: number; min: number; max: number; average: number };
}

export interface Results {
  survey_version: string;
  version_number: number;
  funnel: Funnel;
  fields: FieldResult[];
}

// --- exports ----------------------------------------------------------------

export type ExportStatus = "pending" | "running" | "ready" | "failed";

export interface Export {
  id: string;
  survey_version: string;
  status: ExportStatus;
  include_pii: boolean;
  row_count: number | null;
  error: string;
  created_at: string;
  completed_at: string | null;
}
