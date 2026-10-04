import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, staff } from "@/lib/api";
import { keys, useSurvey, useVersions } from "@/lib/queries";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Spinner,
  StatusBadge,
} from "@/components/ui";

export function SurveyDetailPage() {
  const { surveyId } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();

  const survey = useSurvey(surveyId);
  const versions = useVersions(surveyId);

  const createVersion = useMutation({
    mutationFn: () => staff.createVersion(surveyId as string),
    onSuccess: (version) => {
      client.invalidateQueries({ queryKey: keys.versions(surveyId as string) });
      navigate(`/versions/${version.id}/build`);
    },
  });

  if (survey.isPending || versions.isPending) return <Spinner />;
  if (survey.error) return <ErrorBanner message={String(survey.error)} />;

  const draft = versions.data?.find((version) => version.status === "draft");
  const createError =
    createVersion.error instanceof ApiError ? createVersion.error : null;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{survey.data?.name}</h1>
          <p className="mt-1 text-sm text-muted">{survey.data?.slug}</p>
        </div>
        {draft ? (
          <Button onClick={() => navigate(`/versions/${draft.id}/build`)}>
            Continue draft v{draft.version_number}
          </Button>
        ) : (
          <Button
            onClick={() => createVersion.mutate()}
            disabled={createVersion.isPending}
          >
            {createVersion.isPending ? "Creating…" : "New draft version"}
          </Button>
        )}
      </div>

      {createError && <ErrorBanner message={createError.summary} />}

      {!versions.data?.length ? (
        <EmptyState
          title="No versions yet"
          body="A survey needs a published version before anyone can answer it."
        />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Version</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Published</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {[...versions.data]
                .sort((a, b) => b.version_number - a.version_number)
                .map((version) => (
                  <tr key={version.id} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2.5 font-medium">v{version.version_number}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={version.status} />
                    </td>
                    <td className="px-4 py-2.5 text-muted">
                      {version.published_at
                        ? new Date(version.published_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Link
                        className="text-accent hover:underline"
                        to={`/versions/${version.id}/${
                          version.status === "draft" ? "build" : "results"
                        }`}
                      >
                        {version.status === "draft" ? "Edit" : "Results"}
                      </Link>
                      {version.status === "published" && (
                        <Link
                          className="ml-3 text-accent hover:underline"
                          to={`/start/${version.id}`}
                          target="_blank"
                        >
                          Open as respondent
                        </Link>
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
