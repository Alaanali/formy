import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, staff } from "@/lib/api";
import { keys, useExports } from "@/lib/queries";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Spinner,
  StatusBadge,
} from "@/components/ui";

export function ExportsPage() {
  const { versionId } = useParams();
  const client = useQueryClient();

  // Poll only while something is actually in flight. The flag is derived
  // from the previous render's data, so the query stops polling of its own
  // accord once everything has finished.
  const [polling, setPolling] = useState(true);
  const live = useExports(versionId, polling);

  const anyInFlight = Boolean(
    live.data?.some((row) => row.status === "pending" || row.status === "running"),
  );
  if (polling !== anyInFlight) setPolling(anyInFlight);

  const request = useMutation({
    mutationFn: () => staff.requestExport(versionId as string),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: keys.exports(versionId as string) }),
  });

  if (live.isPending) return <Spinner />;
  if (live.error) {
    const denied = live.error instanceof ApiError && live.error.status === 403;
    return (
      <ErrorBanner
        title={denied ? "Not permitted" : "Could not load exports"}
        message={denied ? "Exporting needs the analyst role on this survey." : String(live.error)}
      />
    );
  }

  async function download(exportId: string) {
    const blob = await staff.downloadExport(exportId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `survey-${exportId}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Exports</h1>
          <p className="mt-1 text-sm text-muted">
            Generated in the background. Whether sensitive columns are included
            is decided from your permissions when you request it, not when you
            download it.
          </p>
        </div>
        <Button onClick={() => request.mutate()} disabled={request.isPending}>
          {request.isPending ? "Requesting…" : "New export"}
        </Button>
      </div>

      {request.error instanceof ApiError && (
        <ErrorBanner message={request.error.summary} />
      )}

      {!live.data?.length ? (
        <EmptyState title="No exports yet" />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Requested</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Rows</th>
                <th className="px-4 py-2.5 font-medium">Sensitive data</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {live.data.map((row) => (
                <tr key={row.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2.5 text-muted">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={row.status} />
                    {row.error && (
                      <p className="mt-1 text-xs text-danger">{row.error}</p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{row.row_count ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    {row.include_pii ? (
                      <Badge tone="warn">included</Badge>
                    ) : (
                      <Badge>redacted</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {row.status === "ready" && (
                      <Button size="sm" variant="ghost" onClick={() => void download(row.id)}>
                        Download
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
