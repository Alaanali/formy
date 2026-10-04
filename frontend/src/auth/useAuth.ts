/** Separated from the provider so each module exports one kind of thing,
 *  which keeps fast refresh working during development. */

import { useContext } from "react";

import { AuthContext } from "./context";
import type { AuthValue } from "./context";

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
