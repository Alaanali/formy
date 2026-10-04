import { Link, NavLink, Outlet, useParams } from "react-router-dom";

import { ThemeToggle } from "./ThemeToggle";
import { Button, StatusBadge } from "./ui";
import { useAuth } from "@/auth/useAuth";
import { useSurvey, useVersion } from "@/lib/queries";

export function Layout() {
  const { session, signOut } = useAuth();
  const { surveyId, versionId } = useParams();

  const version = useVersion(versionId);
  // A version knows its survey, so the trail works on a page that only has
  // a version id in the URL -- which is every builder and analytics page.
  const survey = useSurvey(surveyId ?? version.data?.survey);
  const inContext = Boolean(surveyId || versionId);

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <Mark />
            <span>Survey Platform</span>
          </Link>
          <div className="flex items-center gap-1.5 text-sm">
            <span className="hidden text-muted sm:inline">{session?.username}</span>
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>

        {inContext && (
          <div className="mx-auto max-w-6xl px-6">
            <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 pb-2 text-sm">
              <Link to="/" className="text-muted transition-colors hover:text-ink">
                Organizations
              </Link>
              {survey.data && (
                <>
                  <Chevron />
                  <Link
                    to={`/surveys/${survey.data.id}`}
                    className="font-medium transition-colors hover:text-accent"
                  >
                    {survey.data.name}
                  </Link>
                </>
              )}
              {version.data && (
                <>
                  <Chevron />
                  <span className="flex items-center gap-2 text-muted">
                    Version {version.data.version_number}
                    <StatusBadge status={version.data.status} />
                  </span>
                </>
              )}
            </nav>

            {versionId && (
              <div className="flex gap-1 overflow-x-auto">
                <Tab to={`/versions/${versionId}/build`}>Build</Tab>
                <Tab to={`/versions/${versionId}/results`}>Results</Tab>
                <Tab to={`/versions/${versionId}/responses`}>Responses</Tab>
                <Tab to={`/versions/${versionId}/exports`}>Exports</Tab>
              </div>
            )}
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-7">
        <Outlet />
      </main>
    </div>
  );
}

function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `-mb-px shrink-0 border-b-2 px-3 py-2.5 text-sm transition-colors ${
          isActive
            ? "border-accent font-medium text-accent"
            : "border-transparent text-muted hover:border-line hover:text-ink"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function Chevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden className="text-faint">
      <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function Mark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect width="18" height="18" rx="5" fill="var(--color-accent)" />
      <path d="M5 9.2 7.6 11.8 13 6.4" fill="none" stroke="white" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
