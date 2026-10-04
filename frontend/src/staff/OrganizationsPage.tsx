import { Link } from "react-router-dom";

import { useOrganizations } from "@/lib/queries";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

export function OrganizationsPage() {
  const { data, isPending, error, refetch } = useOrganizations();

  if (isPending) return <Spinner label="Loading organizations…" />;
  if (error) return <ErrorBanner message={String(error)} onRetry={() => void refetch()} />;
  if (!data?.length) {
    return (
      <EmptyState
        title="No organizations"
        body="You are not a member of any organization yet. An owner or admin has to add you."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Organizations</h1>
        <p className="mt-1 text-sm text-muted">
          Surveys belong to an organization, and access is granted per survey
          within it.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {data.map((org) => (
          <Link key={org.id} to={`/organizations/${org.id}/surveys`}>
            <Card className="p-4 transition hover:border-accent">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{org.name}</p>
                  <p className="mt-0.5 text-xs text-muted">{org.slug}</p>
                </div>
                {org.role && <Badge tone="accent">{org.role}</Badge>}
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
