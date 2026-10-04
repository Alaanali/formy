import { useParams } from "react-router-dom";

import { useResults } from "@/lib/queries";
import type { FieldResult } from "@/lib/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

export function ResultsPage() {
  const { versionId } = useParams();
  const { data, isPending, error, refetch } = useResults(versionId);

  if (isPending) return <Spinner label="Loading results…" />;
  if (error) return <ErrorBanner message={String(error)} onRetry={() => void refetch()} />;
  if (!data) return null;

  const { funnel } = data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Results</h1>
        <p className="mt-1 text-sm text-muted">
          Read from pre-aggregated rows, so this stays fast however many
          responses are collected. Refreshes every 10 seconds.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Started" value={funnel.started} />
        <Stat label="Completed" value={funnel.completed} />
        {/* Not "abandoned": nothing marks a stale draft abandoned yet, so
            that counter always reads 0. This is the honest version of the
            same number -- drafts opened and not yet finished. */}
        <Stat label="In progress" value={Math.max(funnel.started - funnel.completed, 0)} />
        <Stat
          label="Completion"
          value={
            funnel.completion_rate === null
              ? "—"
              : `${Math.round(funnel.completion_rate * 100)}%`
          }
        />
      </div>

      {funnel.average_duration_seconds !== null && (
        <p className="text-sm text-muted">
          Median response takes about{" "}
          <strong className="text-ink">
            {formatDuration(funnel.average_duration_seconds)}
          </strong>
          .
        </p>
      )}

      {!data.fields.length ? (
        <EmptyState title="No questions" />
      ) : (
        <div className="space-y-3">
          {data.fields.map((field) => (
            <FieldCard key={field.field_id} field={field} />
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1.5 text-3xl font-semibold tracking-tight tabular-nums">{value}</p>
    </Card>
  );
}

function FieldCard({ field }: { field: FieldResult }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">{field.label ?? field.key ?? field.field_id}</p>
          <p className="mt-0.5 text-xs text-muted">{field.type}</p>
        </div>

        <div className="text-right text-sm">
          <p className="tabular-nums">
            <strong>{field.answered}</strong>
            <span className="text-muted"> of {field.eligible} asked</span>
          </p>
          <p className="text-xs text-muted">
            {/* Derived here, not sent: the payload reports the two counts and
                leaves the arithmetic to the client. Against people shown the
                field, never against all submissions -- for a conditional
                field those differ, and the second number is simply wrong. */}
            {field.eligible === 0
              ? "no one was asked yet"
              : `${Math.round((field.answered / field.eligible) * 100)}% response rate`}
            {field.eligible > field.answered &&
              ` · ${field.eligible - field.answered} skipped`}
          </p>
        </div>
      </div>

      {!field.distribution_available ? (
        <div className="mt-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
          <Badge tone="warn">encrypted</Badge>{" "}
          <span className="ml-1">{field.reason}</span>
        </div>
      ) : (
        <>
          {field.numeric && (
            <dl className="mt-3 grid grid-cols-2 gap-3 rounded-lg bg-raised px-3.5 py-2.5 text-sm sm:grid-cols-4">
              {(
                [
                  ["Average", field.numeric.average],
                  ["Min", field.numeric.min],
                  ["Max", field.numeric.max],
                  ["Sum", field.numeric.sum],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-muted">{label}</dt>
                  <dd className="mt-0.5 font-medium tabular-nums">{round(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          {field.buckets && field.buckets.length > 0 && (
            <ul className="mt-4 space-y-3">
              {field.buckets.map((bucket) => (
                <li key={bucket.bucket} className="text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="truncate font-medium">{bucket.bucket}</span>
                    <span className="shrink-0 tabular-nums text-muted">
                      {bucket.count}
                      {bucket.share !== null && (
                        <span className="ml-1.5 text-ink">
                          {Math.round(bucket.share * 100)}%
                        </span>
                      )}
                    </span>
                  </div>
                  <span className="mt-1 block h-2 overflow-hidden rounded-full bg-line-soft ring-1 ring-line">
                    <span
                      className="block h-full rounded-full bg-accent transition-[width] duration-500"
                      style={{ width: `${Math.round((bucket.share ?? 0) * 100)}%` }}
                    />
                  </span>
                </li>
              ))}
            </ul>
          )}

          {field.buckets?.length === 0 && !field.numeric && (
            <p className="mt-3 text-sm text-muted">
              Free text is not aggregated. Read individual responses instead.
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
