/** The context object and its type, apart from the provider component, so
 *  each module exports one kind of thing and fast refresh keeps working. */

import { createContext } from "react";

export interface Session {
  username: string;
  userId: string;
}

export interface AuthValue {
  session: Session | null;
  status: "checking" | "signed-in" | "signed-out";
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthValue | null>(null);
