/**
 * Staff session.
 *
 * The token lives in localStorage so a reload does not sign the operator
 * out. That is a deliberate trade: it is readable by any script that
 * achieves XSS on this origin, which an httpOnly cookie would not be. The
 * backend issues bearer tokens rather than cookies, so a cookie would mean
 * changing the API; the mitigation here is that the token is revocable
 * server-side and the app renders no untrusted HTML anywhere.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { AuthContext } from "./context";
import type { AuthValue, Session } from "./context";

import { ApiError, auth, getStoredToken, setStoredToken } from "@/lib/api";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  // Derived at initialisation: with no stored token there is nothing to
  // check, so the app should not render a "checking" state it will leave
  // on the very next tick.
  const [status, setStatus] = useState<AuthValue["status"]>(() =>
    getStoredToken() ? "checking" : "signed-out",
  );

  useEffect(() => {
    const token = getStoredToken();
    if (!token) return;
    // A stored token may have been revoked since the last visit, so it is
    // verified rather than trusted.
    auth
      .whoami()
      .then((me) => {
        setSession({ username: me.username, userId: me.user_id });
        setStatus("signed-in");
      })
      .catch(() => {
        setStoredToken(null);
        setStatus("signed-out");
      });
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await auth.login(username, password);
    setStoredToken(result.token);
    setSession({ username: result.username, userId: result.user_id });
    setStatus("signed-in");
  }, []);

  const signOut = useCallback(async () => {
    try {
      // Revoke server-side, so the token is dead everywhere and not merely
      // forgotten by this browser.
      await auth.revoke();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    } finally {
      setStoredToken(null);
      setSession(null);
      setStatus("signed-out");
    }
  }, []);

  const value = useMemo(
    () => ({ session, status, signIn, signOut }),
    [session, status, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
