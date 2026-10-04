import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

import { Button, Card } from "./ui";

/** Without one of these a render error blanks the page with no explanation,
 *  which in production is indistinguishable from the app being down. */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Left for whatever collects console output in the deployed environment.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <Card className="w-full max-w-md p-6 text-center">
          <h1 className="text-lg font-semibold">Something went wrong</h1>
          <p className="mt-2 text-sm text-muted">
            This page could not be displayed. Reloading usually clears it; if
            it does not, the error has been logged.
          </p>
          <Button className="mt-4" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </Card>
      </div>
    );
  }
}
