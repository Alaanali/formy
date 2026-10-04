import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, staff } from "@/lib/api";
import { keys, useSurveys } from "@/lib/queries";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Labelled,
  Spinner,
  inputClass,
} from "@/components/ui";

export function SurveysPage() {
  const { organizationId } = useParams();
  const { data, isPending, error, refetch } = useSurveys(organizationId);
  const [creating, setCreating] = useState(false);

  if (isPending) return <Spinner label="Loading surveys…" />;
  if (error) return <ErrorBanner message={String(error)} onRetry={() => void refetch()} />;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Surveys</h1>
          <p className="mt-1 text-sm text-muted">
            Only surveys you have been granted access to appear here.
          </p>
        </div>
        <Button onClick={() => setCreating((open) => !open)}>
          {creating ? "Cancel" : "New survey"}
        </Button>
      </div>

      {creating && organizationId && (
        <CreateSurveyForm
          organizationId={organizationId}
          onDone={() => setCreating(false)}
        />
      )}

      {!data?.length ? (
        <EmptyState
          title="No surveys yet"
          body="Create one, or ask an admin to grant you access to an existing survey."
        />
      ) : (
        <div className="space-y-2">
          {data.map((survey) => (
            <Link key={survey.id} to={`/surveys/${survey.id}`}>
              <Card className="flex items-center justify-between gap-4 p-4 transition hover:border-accent">
                <div>
                  <p className="font-medium">{survey.name}</p>
                  <p className="mt-0.5 text-xs text-muted">{survey.slug}</p>
                </div>
                <div className="flex items-center gap-2">
                  {survey.published_version ? (
                    <Badge tone="ok">v{survey.published_version} live</Badge>
                  ) : (
                    <Badge tone="warn">unpublished</Badge>
                  )}
                  {survey.my_role && <Badge>{survey.my_role}</Badge>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateSurveyForm({
  organizationId,
  onDone,
}: {
  organizationId: string;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () => staff.createSurvey(organizationId, { name, slug }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.surveys(organizationId) });
      onDone();
    },
  });

  const error = create.error instanceof ApiError ? create.error : null;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Card className="p-4">
      <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Labelled label="Name" htmlFor="name" error={error?.forField("name")}>
          <input
            id="name"
            className={inputClass}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              // Slug follows the name until the operator edits it, which is
              // what people expect and avoids a second required field.
              setSlug(
                e.target.value
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, "-")
                  .replace(/^-|-$/g, ""),
              );
            }}
            required
          />
        </Labelled>

        <Labelled
          label="Slug"
          htmlFor="slug"
          hint="Unique within this organization."
          error={error?.forField("slug")}
        >
          <input
            id="slug"
            className={inputClass}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
          />
        </Labelled>

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create"}
        </Button>
      </form>

      {error && !error.forField("slug") && !error.forField("name") && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error.summary}
        </p>
      )}
    </Card>
  );
}
