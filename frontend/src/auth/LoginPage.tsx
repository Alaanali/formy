import { useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "./useAuth";
import { ApiError } from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button, Card, Labelled, inputClass } from "@/components/ui";

export function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
    } catch (caught) {
      // The backend returns one message for every failure, so the endpoint
      // cannot be used to discover which usernames exist. Showing it
      // verbatim keeps that property.
      setError(
        caught instanceof ApiError ? caught.summary : "Could not sign in. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-5 flex items-center justify-between">
          <span className="flex items-center gap-2 font-semibold">
            <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden>
              <rect width="18" height="18" rx="5" fill="var(--color-accent)" />
              <path
                d="M5 9.2 7.6 11.8 13 6.4"
                fill="none"
                stroke="white"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Survey Platform
          </span>
          <ThemeToggle />
        </div>

      <Card className="w-full p-6 shadow-pop">
        <h1 className="text-xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-muted">
          Staff access to surveys, results and exports.
        </p>

        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <Labelled label="Username" htmlFor="username">
            <input
              id="username"
              className={inputClass}
              value={username}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </Labelled>

          <Labelled label="Password" htmlFor="password">
            <input
              id="password"
              type="password"
              className={inputClass}
              value={password}
              autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Labelled>

          {error && (
            <p role="alert" className="text-sm font-medium text-danger">
              {error}
            </p>
          )}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
          Seeded by <code className="font-mono">make bootstrap</code>:{" "}
          <code className="font-mono">demo-owner</code>,{" "}
          <code className="font-mono">demo-admin</code> or{" "}
          <code className="font-mono">demo-analyst</code>, password{" "}
          <code className="font-mono">demo-password</code>.
        </p>
      </Card>
      </div>
    </div>
  );
}
