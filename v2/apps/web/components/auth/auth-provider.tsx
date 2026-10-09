"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo
} from "react";
import { apiRequest, ApiError } from "@/lib/api-client";
import type { AuthenticatedUser, SessionResponse } from "@/lib/domain";

type LoginCredentials = {
  handle: string;
  password: string;
};

type AuthContextValue = {
  user: AuthenticatedUser | null;
  isLoading: boolean;
  login: (credentials: LoginCredentials) => Promise<AuthenticatedUser>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
};

const SESSION_QUERY_KEY = ["session", "current-user"] as const;
const AuthContext = createContext<AuthContextValue | null>(null);

async function loadCurrentUser(): Promise<AuthenticatedUser | null> {
  try {
    return await apiRequest<AuthenticatedUser>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

type AuthProviderProps = {
  children: ReactNode;
};

// PUBLIC_INTERFACE
/**
 * Hydrates the signed HttpOnly demo session and exposes role-aware browser helpers.
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const queryClient = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: loadCurrentUser,
    retry: false
  });

  const login = useCallback(
    async (credentials: LoginCredentials) => {
      const session = await apiRequest<SessionResponse>("/auth/login", {
        method: "POST",
        body: credentials
      });
      queryClient.setQueryData(SESSION_QUERY_KEY, session.user);
      return session.user;
    },
    [queryClient]
  );

  const logout = useCallback(async () => {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST" });
    } finally {
      queryClient.setQueryData(SESSION_QUERY_KEY, null);
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "session"
      });
    }
  }, [queryClient]);

  const user = sessionQuery.data ?? null;
  const hasPermission = useCallback(
    (permission: string) =>
      Boolean(
        user &&
          (user.permissions.includes("*") || user.permissions.includes(permission))
      ),
    [user]
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading: sessionQuery.isLoading,
      login,
      logout,
      hasPermission
    }),
    [hasPermission, login, logout, sessionQuery.isLoading, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// PUBLIC_INTERFACE
/**
 * Returns the current authenticated session and permission helpers.
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}
