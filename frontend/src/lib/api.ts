/**
 * The single place that talks to the backend.
 *
 * Two credentials exist and they are deliberately never mixed: staff hold an
 * `Authorization: Token` issued by /auth/token/, respondents hold an
 * `X-Resume-Token` for one submission. A respondent's token must never reach
 * a staff endpoint and vice versa, so the caller states which it is sending.
 */

import type {
  Answers,
  Export,
  Organization,
  Results,
  Section,
  StartedSubmission,
  SubmissionAnswers,
  SubmissionState,
  SubmissionFile,
  SubmissionSummary,
  Survey,
  SurveyVersion,
  SurveyVersionWithSchema,
  TokenResponse,
} from "./types";

// Relative by default, so the dev server's proxy and a same-origin
// production deployment both work without configuration. Set VITE_API_BASE
// to an absolute URL when the app is served from a different origin than the
// API -- which is also what lets the integration suite run outside a browser,
// where a relative URL has nothing to resolve against.
const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export const TOKEN_STORAGE_KEY = "survey.staff.token";

/** Field-keyed errors, which is how the backend reports validation. */
export type FieldErrors = Record<string, string | string[]>;

export class ApiError extends Error {
  status: number;
  errors: FieldErrors;
  constructor(status: number, message: string, errors: FieldErrors = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }

  /** A readable line for a field, whichever shape the backend used. */
  forField(fieldId: string): string | undefined {
    const raw = this.errors[fieldId];
    if (!raw) return undefined;
    return Array.isArray(raw) ? raw.join(" ") : String(raw);
  }

  get summary(): string {
    const general = this.errors.__all__ ?? this.errors.detail;
    if (general) return Array.isArray(general) ? general.join(" ") : String(general);
    const first = Object.values(this.errors)[0];
    if (first) return Array.isArray(first) ? first.join(" ") : String(first);
    return this.message;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** A respondent's bearer token for one submission. */
  resumeToken?: string;
  /** Opt out of the staff token, for genuinely anonymous calls. */
  anonymous?: boolean;
  signal?: AbortSignal;
  raw?: boolean;
}

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    // Private browsing, or storage disabled. Treat as signed out rather
    // than crashing the whole app on boot.
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* ignore: the in-memory session still works for this tab */
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, resumeToken, anonymous, signal, raw } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (resumeToken) headers["X-Resume-Token"] = resumeToken;

  // A respondent call never carries the staff token: sending both would let
  // a signed-in operator silently act as the respondent.
  if (!anonymous && !resumeToken) {
    const token = getStoredToken();
    if (token) headers.Authorization = `Token ${token}`;
  }

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (response.status === 204) return undefined as T;

  if (raw) {
    if (!response.ok) throw new ApiError(response.status, response.statusText);
    return (await response.blob()) as T;
  }

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (!response.ok) {
    const errors =
      payload && typeof payload === "object" && "errors" in payload
        ? ((payload as { errors: FieldErrors }).errors ?? {})
        : ((payload as FieldErrors) ?? {});
    throw new ApiError(response.status, response.statusText, errors);
  }

  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 200) };
  }
}

// --- auth -------------------------------------------------------------------

export const auth = {
  login: (username: string, password: string) =>
    request<TokenResponse>("/auth/token/", {
      method: "POST",
      body: { username, password },
      anonymous: true,
    }),
  whoami: () => request<{ user_id: string; username: string }>("/auth/whoami/"),
  revoke: () => request<void>("/auth/token/revoke/", { method: "POST" }),
};

// --- staff ------------------------------------------------------------------

export const staff = {
  organizations: () => request<Organization[]>("/organizations/"),

  surveys: (organizationId: string) =>
    request<Survey[]>(`/organizations/${organizationId}/surveys/`),

  createSurvey: (organizationId: string, body: { name: string; slug: string }) =>
    request<Survey>(`/organizations/${organizationId}/surveys/`, {
      method: "POST",
      body,
    }),

  survey: (surveyId: string) => request<Survey>(`/surveys/${surveyId}/`),

  updateSurvey: (surveyId: string, body: Partial<Pick<Survey, "name" | "slug">>) =>
    request<Survey>(`/surveys/${surveyId}/`, { method: "PATCH", body }),

  deleteSurvey: (surveyId: string) =>
    request<void>(`/surveys/${surveyId}/`, { method: "DELETE" }),

  versions: (surveyId: string) => request<SurveyVersion[]>(`/surveys/${surveyId}/versions/`),

  /** Derives from the latest published version, preserving field ids. */
  createVersion: (surveyId: string) =>
    request<SurveyVersion>(`/surveys/${surveyId}/versions/`, { method: "POST" }),

  version: (versionId: string) =>
    request<SurveyVersionWithSchema>(`/versions/${versionId}/`),

  sections: (versionId: string) => request<Section[]>(`/versions/${versionId}/sections/`),

  createSection: (versionId: string, body: Omit<Section, "id" | "version">) =>
    request<Section>(`/versions/${versionId}/sections/`, { method: "POST", body }),

  updateSection: (sectionId: string, body: Partial<Section>) =>
    request<Section>(`/sections/${sectionId}/`, { method: "PATCH", body }),

  deleteSection: (sectionId: string) =>
    request<void>(`/sections/${sectionId}/`, { method: "DELETE" }),

  publish: (versionId: string) =>
    request<SurveyVersionWithSchema>(`/versions/${versionId}/publish/`, { method: "POST" }),

  results: (versionId: string) => request<Results>(`/versions/${versionId}/results/`),

  surveyResults: (surveyId: string) => request<Results>(`/surveys/${surveyId}/results/`),

  submissions: (versionId: string) =>
    request<SubmissionSummary[]>(`/versions/${versionId}/submissions/`),

  submissionAnswers: (submissionId: string) =>
    request<SubmissionAnswers>(`/submissions/${submissionId}/answers/`),

  exports: (versionId: string) => request<Export[]>(`/versions/${versionId}/exports/`),

  requestExport: (versionId: string) =>
    request<Export>(`/versions/${versionId}/exports/`, { method: "POST" }),

  /** Fetch an uploaded file and hand it to the browser to save.
   *
   *  Not a plain <a href>: the endpoint is token-authenticated and gated on
   *  the PII capability, so the request has to carry the Authorization
   *  header. The response is already an attachment; this only gives the save
   *  dialog the filename the server chose.
   */
  downloadFile: async (fileId: string): Promise<void> => {
    const response = await fetch(`${BASE}/files/${fileId}/download/`, {
      headers: getStoredToken() ? { Authorization: `Token ${getStoredToken()}` } : {},
    });
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText, {});
    }

    const disposition = response.headers.get("content-disposition") ?? "";
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = match ? decodeURIComponent(match[1]) : fileId;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },

  downloadExport: (exportId: string) =>
    request<Blob>(`/exports/${exportId}/download/`, { raw: true }),
};

// --- respondent -------------------------------------------------------------

export const respondent = {
  start: (versionId: string) =>
    request<StartedSubmission>(`/public/versions/${versionId}/submissions/`, {
      method: "POST",
      anonymous: true,
    }),

  state: (submissionId: string, resumeToken: string) =>
    request<SubmissionState>(`/public/submissions/${submissionId}/`, { resumeToken }),

  save: (submissionId: string, resumeToken: string, answers: Answers) =>
    request<SubmissionState>(`/public/submissions/${submissionId}/`, {
      method: "PATCH",
      body: { answers },
      resumeToken,
    }),

  /** Phase one of a file answer. Multipart rather than JSON: base64 inside
   *  a JSON body inflates the payload by a third and buffers it twice. */
  upload: async (
    submissionId: string,
    resumeToken: string,
    fieldId: string,
    file: File,
  ): Promise<SubmissionFile> => {
    const form = new FormData();
    form.append("field_id", fieldId);
    form.append("file", file);

    const response = await fetch(`${BASE}/public/submissions/${submissionId}/files/`, {
      method: "POST",
      // No Content-Type: the browser sets it with the multipart boundary.
      headers: { Accept: "application/json", "X-Resume-Token": resumeToken },
      body: form,
    });

    const payload = await response.text();
    const parsed = payload ? safeJson(payload) : null;
    if (!response.ok) {
      const errors =
        parsed && typeof parsed === "object" && "errors" in parsed
          ? ((parsed as { errors: FieldErrors }).errors ?? {})
          : ((parsed as FieldErrors) ?? {});
      throw new ApiError(response.status, response.statusText, errors);
    }
    return parsed as SubmissionFile;
  },

  submit: (submissionId: string, resumeToken: string, answers: Answers = {}) =>
    request<{ id: string; status: string; submitted_at: string }>(
      `/public/submissions/${submissionId}/submit/`,
      { method: "POST", body: { answers }, resumeToken },
    ),
};
