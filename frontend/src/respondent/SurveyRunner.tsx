/** The respondent's multi-step form. */

import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { FieldRenderer } from "./FieldRenderer";
import { useSubmission } from "./useSubmission";
import { missingRequired, visibleOptions } from "@/lib/logic";
import { Button, Card, ErrorBanner, Spinner } from "@/components/ui";

export function SurveyRunner() {
  const { submissionId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const resumeToken = params.get("t") ?? undefined;

  const session = useSubmission(submissionId, resumeToken);
  const [requestedStep, setRequestedStep] = useState(0);
  const [attempted, setAttempted] = useState(false);

  const { sections, visible, required, answers, state } = session;

  // A section can disappear while the respondent is standing on it -- answer
  // "Egypt" and the Saudi-only section goes away. Clamped during render
  // rather than corrected in an effect, so there is never a frame showing a
  // step that no longer exists.
  const stepIndex = Math.min(requestedStep, Math.max(sections.length - 1, 0));
  const section = sections[stepIndex];

  const sectionFieldIds = useMemo(
    () => (section ? section.fields.filter((id) => visible[id]) : []),
    [section, visible],
  );

  const outstanding = useMemo(
    () => missingRequired(sectionFieldIds, answers, visible, required),
    [sectionFieldIds, answers, visible, required],
  );

  if (session.loading) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <Spinner label="Loading your survey…" />
      </div>
    );
  }

  if (session.loadError) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <ErrorBanner title="Cannot open this survey" message={session.loadError} />
      </div>
    );
  }

  if (session.completed) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <Card className="p-10 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-ok-soft text-ok ring-1 ring-ok/25">
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="m5 12.5 4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <h1 className="mt-4 text-xl font-semibold tracking-tight">Thank you</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted">
            Your responses have been recorded. This link is now closed.
          </p>
        </Card>
      </div>
    );
  }

  if (!state || !section) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <ErrorBanner title="Nothing to answer" message="This survey has no visible questions." />
      </div>
    );
  }

  const isLast = stepIndex === sections.length - 1;

  async function onNext() {
    setAttempted(true);
    if (outstanding.length > 0) return;
    await session.flush();
    setAttempted(false);
    if (isLast) {
      const ok = await session.submit();
      if (ok) navigate(`/s/${submissionId}/done`, { replace: true });
    } else {
      setRequestedStep(stepIndex + 1);
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <header className="mb-5">
        {state.survey && (
          <p className="mb-3 text-sm font-medium text-muted">{state.survey}</p>
        )}
        <div className="flex items-center justify-between text-xs text-muted">
          <span>
            Step {stepIndex + 1} of {sections.length}
          </span>
          <SaveIndicator session={session} />
        </div>

        {/* One segment per section, so the shape of what is left is visible
            rather than a single percentage. Sections can disappear mid-form,
            which is why this is derived from the live list every render. */}
        <div
          className="mt-2 flex gap-1.5"
          role="progressbar"
          aria-valuenow={stepIndex + 1}
          aria-valuemin={1}
          aria-valuemax={sections.length}
        >
          {sections.map((entry, index) => (
            <span
              key={entry.key}
              className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
                index < stepIndex
                  ? "bg-accent/45"
                  : index === stepIndex
                    ? "bg-accent"
                    : "bg-line"
              }`}
            />
          ))}
        </div>

        <ol className="mt-2.5 hidden gap-4 text-xs sm:flex">
          {sections.map((entry, index) => (
            <li
              key={entry.key}
              className={
                index === stepIndex ? "font-medium text-ink" : "truncate text-faint"
              }
            >
              {entry.title}
            </li>
          ))}
        </ol>
      </header>

      <Card className="p-6 sm:p-7">
        <h1 className="text-xl font-semibold tracking-tight">{section.title}</h1>

        <div className="mt-6 space-y-6">
          {sectionFieldIds.map((fieldId) => {
            const field = state.schema.fields[fieldId];
            if (!field) return null;
            return (
              <FieldRenderer
                key={fieldId}
                fieldId={fieldId}
                field={field}
                value={answers[fieldId] ?? null}
                options={visibleOptions(field, state.schema, answers, visible)}
                required={Boolean(required[fieldId])}
                error={
                  session.fieldErrors[fieldId] ??
                  (attempted && outstanding.includes(fieldId)
                    ? "This question needs an answer."
                    : undefined)
                }
                submissionId={submissionId as string}
                resumeToken={resumeToken as string}
                onChange={(value) => session.setAnswer(fieldId, value)}
              />
            );
          })}
        </div>

        {attempted && outstanding.length > 0 && (
          <p role="alert" className="mt-4 text-sm font-medium text-danger">
            {outstanding.length} question{outstanding.length === 1 ? "" : "s"} still need
            {outstanding.length === 1 ? "s" : ""} an answer.
          </p>
        )}

        <div className="mt-7 flex items-center justify-between border-t border-line pt-5">
          <Button
            variant="secondary"
            disabled={stepIndex === 0}
            onClick={() => {
              setAttempted(false);
              setRequestedStep(Math.max(0, stepIndex - 1));
            }}
          >
            Back
          </Button>
          <Button onClick={onNext} className="min-w-28">
            {isLast ? "Submit" : "Continue"}
          </Button>
        </div>
      </Card>

      <p className="mt-5 text-center text-xs text-muted">
        Your answers save as you go — you can close this page and return with
        the same link.
      </p>
    </div>
  );
}

function SaveIndicator({ session }: { session: ReturnType<typeof useSubmission> }) {
  const { saveState } = session;
  if (saveState.kind === "saving") return <span className="text-muted">Saving…</span>;
  if (saveState.kind === "saved")
    return (
      <span className="flex items-center gap-1 text-ok">
        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="3">
          <path d="m5 12.5 4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Saved
      </span>
    );
  if (saveState.kind === "error") return <span className="text-danger">{saveState.message}</span>;
  return <span />;
}
