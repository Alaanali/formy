import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import { useAuth } from "@/auth/useAuth";
import { LoginPage } from "@/auth/LoginPage";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { DonePage } from "@/respondent/DonePage";
import { StartPage } from "@/respondent/StartPage";
import { SurveyRunner } from "@/respondent/SurveyRunner";
import { ExportsPage } from "@/staff/ExportsPage";
import { OrganizationsPage } from "@/staff/OrganizationsPage";
import { ResultsPage } from "@/staff/ResultsPage";
import { SubmissionsPage } from "@/staff/SubmissionsPage";
import { SurveyDetailPage } from "@/staff/SurveyDetailPage";
import { SurveysPage } from "@/staff/SurveysPage";
import { VersionBuilderPage } from "@/staff/VersionBuilderPage";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Respondent routes are outside the authenticated shell entirely.
            They are answered anonymously, and the two credential paths are
            kept visibly separate. */}
        <Route path="/start/:versionId" element={<StartPage />} />
        <Route path="/s/:submissionId" element={<SurveyRunner />} />
        <Route path="/s/:submissionId/done" element={<DonePage />} />

        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route index element={<OrganizationsPage />} />
            <Route path="/organizations/:organizationId/surveys" element={<SurveysPage />} />
            <Route path="/surveys/:surveyId" element={<SurveyDetailPage />} />
            <Route path="/versions/:versionId/build" element={<VersionBuilderPage />} />
            <Route path="/versions/:versionId/results" element={<ResultsPage />} />
            <Route path="/versions/:versionId/responses" element={<SubmissionsPage />} />
            <Route path="/versions/:versionId/exports" element={<ExportsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

function RequireAuth() {
  const { status } = useAuth();

  if (status === "checking") {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner label="Checking your session…" />
      </div>
    );
  }
  if (status === "signed-out") return <LoginPage />;

  // Rendered by the nested <Route element={<Layout />}>.
  return <Outlet />;
}

