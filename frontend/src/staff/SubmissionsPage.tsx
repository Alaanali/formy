import { useState } from "react";
import { useParams } from "react-router-dom";

import { useSubmissionAnswers, useSubmissions, useVersion } from "@/lib/queries";
import { ApiError, staff } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Spinner,
  StatusBadge,
} from "@/components/ui";

export function SubmissionsPage() {
  const { versionId } = useParams();
  const { data, isPending, error } = useSubmissions(versionId);
  const [open, setOpen] = useState<string | null>(null);

  if (isPending) return <Spinner label="Loading responses…" />;
  if (error) {
    const denied = error instanceof ApiError && error.status === 403;
    return (
      <ErrorBanner
        title={denied ? "Not permitted" : "Could not load responses"}
        message={
          denied
            ? "Reading individual responses needs the analyst role on this survey. Aggregate results are still available."
            : String(error)
        }
      />
    );
  }

  if (!data?.length) {
    return <EmptyState title="No responses yet" body="Share the survey link to collect some." />;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Responses</h1>
        <p className="mt-1 text-sm text-muted">
          Opening one is recorded in the audit log, and sensitive answers are
          decrypted only if your role allows it.
        </p>
      </div>

      <Card>
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Started</th>
              <th className="px-4 py-2.5 font-medium">Submitted</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {data.map((submission) => (
              <tr key={submission.id} className="border-b border-line/60 last:border-0">
                <td className="px-4 py-2.5 text-muted">
                  {new Date(submission.started_at).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-muted">
                  {submission.submitted_at
                    ? new Date(submission.submitted_at).toLocaleString()
                    : "—"}
                </td>
                <td className="px-4 py-2.5">
                  <StatusBadge status={submission.status} />
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setOpen((current) => (current === submission.id ? null : submission.id))
                    }
                  >
                    {open === submission.id ? "Hide" : "View"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {open && <AnswerPanel submissionId={open} versionId={versionId} />}
    </div>
  );
}

function AnswerPanel({
  submissionId,
  versionId,
}: {
  submissionId: string;
  versionId: string | undefined;
}) {
  const answers = useSubmissionAnswers(submissionId);
  const version = useVersion(versionId);

  if (answers.isPending) return <Spinner label="Decrypting…" />;
  if (answers.error) {
    const denied = answers.error instanceof ApiError && answers.error.status === 403;
    return (
      <ErrorBanner
        title={denied ? "Not permitted" : "Could not load"}
        message={
          denied
            ? "Reading an individual response needs the analyst role on this survey."
            : String(answers.error)
        }
      />
    );
  }

  const schema = version.data?.schema;

  return (
    <Card className="p-4">
      <h2 className="font-medium">Response</h2>
      <dl className="mt-3 space-y-2.5">
        {Object.entries(answers.data?.answers ?? {}).map(([fieldId, value]) => {
          const field = schema?.fields[fieldId];
          const redacted =
            value !== null && typeof value === "object" && "__redacted__" in value;
          // A file answer stores the upload's id. Rendering it raw showed a
          // staff viewer a bare UUID with no way to open what was attached.
          const isFile = field?.type === "file" && typeof value === "string" && value !== "";

          return (
            <div key={fieldId} className="grid gap-1 sm:grid-cols-[1fr_2fr]">
              <dt className="text-sm text-muted">{field?.label ?? field?.key ?? fieldId}</dt>
              <dd className="text-sm">
                {redacted ? (
                  <Badge tone="warn">redacted — your role cannot read this</Badge>
                ) : isFile ? (
                  <FileAnswer fileId={value as string} />
                ) : Array.isArray(value) ? (
                  value.join(", ")
                ) : value === null || value === "" ? (
                  <span className="text-muted">not answered</span>
                ) : (
                  String(value)
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </Card>
  );
}

function FileAnswer({ fileId }: { fileId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        variant="secondary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await staff.downloadFile(fileId);
          } catch (caught) {
            // 403 is the usual one: downloading an attachment needs the PII
            // capability, because a filename alone often identifies someone.
            setError(
              caught instanceof ApiError && caught.status === 403
                ? "Your role cannot open attachments."
                : "Could not download this file.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Downloading…" : "Download attachment"}
      </Button>
      {error && <span className="text-xs font-medium text-danger">{error}</span>}
    </span>
  );
}
