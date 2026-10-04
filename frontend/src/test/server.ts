/** A stand-in backend for component tests, shaped like the real one. */

import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import fixtures from "./parity-fixtures.json";

export const SCHEMA = fixtures.schema;
export const FIELD = Object.fromEntries(
  Object.entries(SCHEMA.fields).map(([id, definition]) => [
    (definition as { key: string }).key,
    id,
  ]),
) as Record<string, string>;

export const SUBMISSION_ID = "01a0f000-0000-7000-8000-000000000001";
export const TOKEN = "resume-token-for-tests";

/** Records what the component actually sent, so tests can assert on it. */
export const saved: Array<Record<string, unknown>> = [];
let submitted = false;

/** Read through a function so tests see the current value, not a snapshot
 *  captured at import time. */
export function wasSubmitted(): boolean {
  return submitted;
}

export function reset() {
  saved.length = 0;
  submitted = false;
}

function state(answers: Record<string, unknown>) {
  // Mirrors what the real backend returns: its own resolution, which the
  // client reconciles against.
  return {
    id: SUBMISSION_ID,
    status: "in_progress",
    started_at: new Date().toISOString(),
    last_activity_at: new Date().toISOString(),
    submitted_at: null,
    resume_expires_at: null,
    schema: SCHEMA,
    answers,
    visible: {},
    required: {},
    options: {},
  };
}

let current: Record<string, unknown> = {};

/** Added per-test, so the default schema stays minimal. */
export function uploadsEnabled(options: { reject?: string } = {}) {
  const fieldId = FIELD.attachment;
  server.use(
    http.post(`/api/v1/public/submissions/${SUBMISSION_ID}/files/`, async () => {
      if (options.reject) {
        return HttpResponse.json({ errors: { file: options.reject } }, { status: 400 });
      }
      return HttpResponse.json(
        {
          id: "01a0f000-0000-7000-8000-00000000f11e",
          field_id: fieldId,
          original_name: "cv.pdf",
          content_type: "application/pdf",
          size_bytes: 8,
        },
        { status: 201 },
      );
    }),
  );
}

export const handlers = [
  http.post("/api/v1/auth/token/", async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string };
    if (body.password !== "correct") {
      return HttpResponse.json({ detail: "Invalid credentials." }, { status: 400 });
    }
    return HttpResponse.json({ token: "staff-token", user_id: "u1", username: body.username });
  }),

  http.get("/api/v1/auth/whoami/", ({ request }) =>
    request.headers.get("Authorization")
      ? HttpResponse.json({ user_id: "u1", username: "demo-admin" })
      : new HttpResponse(null, { status: 401 }),
  ),

  http.get(`/api/v1/public/submissions/${SUBMISSION_ID}/`, ({ request }) => {
    if (request.headers.get("X-Resume-Token") !== TOKEN) {
      return new HttpResponse(null, { status: 403 });
    }
    return HttpResponse.json(state(current));
  }),

  http.patch(`/api/v1/public/submissions/${SUBMISSION_ID}/`, async ({ request }) => {
    if (request.headers.get("X-Resume-Token") !== TOKEN) {
      return new HttpResponse(null, { status: 403 });
    }
    const body = (await request.json()) as { answers: Record<string, unknown> };
    saved.push(body.answers);

    if (body.answers[FIELD.age] === 999) {
      return HttpResponse.json(
        { errors: { [FIELD.age]: "must be at most 120" } },
        { status: 400 },
      );
    }

    current = { ...current, ...body.answers };
    return HttpResponse.json(state(current));
  }),

  http.post(`/api/v1/public/submissions/${SUBMISSION_ID}/submit/`, () => {
    submitted = true;
    return HttpResponse.json({
      id: SUBMISSION_ID,
      status: "completed",
      submitted_at: new Date().toISOString(),
    });
  }),
];

export const server = setupServer(...handlers);

export function resetAnswers() {
  current = {};
}
