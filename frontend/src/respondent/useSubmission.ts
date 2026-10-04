/**
 * The respondent's session: local answers, local conditional logic, and
 * debounced autosave reconciled against the server.
 *
 * The shape of the problem: the server is authoritative about visibility,
 * but waiting for a round trip before showing or hiding a field makes the
 * form feel broken. So answers and visibility are computed locally for
 * instant feedback, and every save returns the server's own resolution,
 * which replaces the local one. If they ever disagree, the server wins and
 * the discrepancy is surfaced rather than hidden.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, respondent } from "@/lib/api";
import { resolveRequired, resolveVisibility, visibleSections } from "@/lib/logic";
import type { AnswerValue, Answers, SubmissionState } from "@/lib/types";

const AUTOSAVE_DELAY_MS = 800;

export type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; at: number }
  | { kind: "error"; message: string };

export interface SubmissionSession {
  state: SubmissionState | null;
  answers: Answers;
  visible: Record<string, boolean>;
  required: Record<string, boolean>;
  sections: ReturnType<typeof visibleSections>;
  fieldErrors: Record<string, string>;
  saveState: SaveState;
  loading: boolean;
  loadError: string | null;
  completed: boolean;
  setAnswer: (fieldId: string, value: AnswerValue) => void;
  flush: () => Promise<void>;
  submit: () => Promise<boolean>;
  reload: () => void;
}

export function useSubmission(
  submissionId: string | undefined,
  resumeToken: string | undefined,
): SubmissionSession {
  const [state, setState] = useState<SubmissionState | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  // Answers changed since the last successful save, holding the values
  // themselves rather than just their ids. Keeping the values here avoids
  // reading state through a ref during render, and means only what actually
  // changed is sent -- a slow request cannot overwrite newer values with
  // stale ones.
  const pending = useRef<Map<string, AnswerValue>>(new Map());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!submissionId || !resumeToken) return;
    let cancelled = false;

    respondent
      .state(submissionId, resumeToken)
      .then((loaded) => {
        if (cancelled) return;
        setState(loaded);
        setAnswers(loaded.answers ?? {});
        setCompleted(loaded.status === "completed");
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(
          error instanceof ApiError && error.status === 403
            ? "This link is no longer valid. It may have expired, or the survey may already be submitted."
            : "Could not load this submission.",
        );
      });

    return () => {
      cancelled = true;
    };
  }, [submissionId, resumeToken, reloadToken]);

  // Derived rather than tracked: there is nothing to show until either the
  // state or an error has arrived, and deriving avoids a state write inside
  // the effect that starts the fetch.
  const loading = Boolean(submissionId && resumeToken) && state === null && loadError === null;

  const schema = state?.schema ?? null;

  // Local resolution for instant feedback. Falls back to the server's last
  // answer if the schema has not arrived yet.
  const visible = useMemo(
    () => (schema ? resolveVisibility(schema, answers) : (state?.visible ?? {})),
    [schema, answers, state?.visible],
  );

  const required = useMemo(
    () => (schema ? resolveRequired(schema, answers, visible) : (state?.required ?? {})),
    [schema, answers, visible, state?.required],
  );

  const sections = useMemo(
    () => (schema ? visibleSections(schema, visible) : []),
    [schema, visible],
  );

  const save = useCallback(async () => {
    if (!submissionId || !resumeToken || pending.current.size === 0) return;

    const sending = new Map(pending.current);
    pending.current.clear();

    const payload: Answers = {};
    for (const [fieldId, value] of sending) {
      // Never send an answer to a field the logic now hides: the server
      // would discard it anyway, and sending it muddies the intent.
      if (visible[fieldId]) payload[fieldId] = value;
    }
    if (Object.keys(payload).length === 0) return;

    setSaveState({ kind: "saving" });
    try {
      const next = await respondent.save(submissionId, resumeToken, payload);
      setState(next);
      setFieldErrors({});
      setSaveState({ kind: "saved", at: Date.now() });
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        // Per-field problems: show them inline rather than as a banner.
        const mapped: Record<string, string> = {};
        for (const [fieldId, message] of Object.entries(error.errors)) {
          mapped[fieldId] = Array.isArray(message) ? message.join(" ") : String(message);
        }
        setFieldErrors(mapped);
        setSaveState({ kind: "idle" });
      } else {
        // Put the values back so the next attempt retries them rather than
        // losing what was typed. Anything edited since keeps priority.
        for (const [fieldId, value] of sending) {
          if (!pending.current.has(fieldId)) pending.current.set(fieldId, value);
        }
        setSaveState({
          kind: "error",
          message:
            error instanceof ApiError && error.status === 403
              ? "This link is no longer valid."
              : "Could not save. Your answers are kept and will retry.",
        });
      }
    }
  }, [submissionId, resumeToken, visible]);

  const setAnswer = useCallback(
    (fieldId: string, value: AnswerValue) => {
      setAnswers((previous) => ({ ...previous, [fieldId]: value }));
      pending.current.set(fieldId, value);
      setFieldErrors((previous) => {
        if (!previous[fieldId]) return previous;
        const { [fieldId]: _dropped, ...rest } = previous;
        return rest;
      });

      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void save(), AUTOSAVE_DELAY_MS);
    },
    [save],
  );

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    await save();
  }, [save]);

  const submit = useCallback(async () => {
    if (!submissionId || !resumeToken) return false;
    if (timer.current) clearTimeout(timer.current);
    await save();

    try {
      // Nothing extra to send: every answer was already saved above, and
      // the server drops answers to hidden fields itself at submit.
      await respondent.submit(submissionId, resumeToken, {});
      setCompleted(true);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        const mapped: Record<string, string> = {};
        for (const [fieldId, message] of Object.entries(error.errors)) {
          mapped[fieldId] = Array.isArray(message) ? message.join(" ") : String(message);
        }
        setFieldErrors(mapped);
      } else {
        setSaveState({ kind: "error", message: "Could not submit. Try again." });
      }
      return false;
    }
  }, [submissionId, resumeToken, save]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return {
    state,
    answers,
    visible,
    required,
    sections,
    fieldErrors,
    saveState,
    loading,
    loadError,
    completed,
    setAnswer,
    flush,
    submit,
    reload: () => {
      // Clearing the state is what puts the hook back into its loading
      // shape, since loading is derived from it.
      setState(null);
      setLoadError(null);
      setReloadToken((n) => n + 1);
    },
  };
}
