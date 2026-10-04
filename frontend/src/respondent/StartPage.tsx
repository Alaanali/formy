/** Opens a new submission against a published version and hands over the
 *  resume link. The token appears in the URL here and only here -- it is a
 *  bearer credential, so it is passed to the API as a header afterwards. */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, respondent } from "@/lib/api";
import { Card, ErrorBanner, Spinner } from "@/components/ui";

export function StartPage() {
  const { versionId } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  // StrictMode double-invokes effects in development; without this guard a
  // respondent would silently create two drafts.
  const started = useRef(false);

  useEffect(() => {
    if (!versionId || started.current) return;
    started.current = true;

    respondent
      .start(versionId)
      .then((submission) => {
        navigate(`/s/${submission.id}?t=${encodeURIComponent(submission.resume_token)}`, {
          replace: true,
        });
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof ApiError && caught.status === 404
            ? "This survey is not open. It may not be published yet."
            : caught instanceof ApiError && caught.status === 429
              ? "Too many attempts from this network. Please try again later."
              : "Could not start the survey.",
        );
      });
  }, [versionId, navigate]);

  return (
    <div className="mx-auto max-w-lg p-8">
      {error ? (
        <ErrorBanner title="Cannot start" message={error} />
      ) : (
        <Card className="p-8">
          <Spinner label="Opening the survey…" />
        </Card>
      )}
    </div>
  );
}
