"use client";

import Link from "next/link";
import { type ReactNode } from "react";
import { PermissionState } from "@/components/states/content-state";
import { PageSkeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/components/auth/auth-provider";
import { roleLabel } from "@/lib/domain";

type PermissionBoundaryProps = {
  permission: string;
  children: ReactNode;
};

// PUBLIC_INTERFACE
/**
 * Presents a safe route state when the current API session lacks a permission.
 */
export function PermissionBoundary({
  permission,
  children
}: PermissionBoundaryProps) {
  const { isLoading, user, hasPermission } = useAuth();

  if (isLoading) {
    return <PageSkeleton />;
  }

  if (!user) {
    return (
      <PermissionState
        action={
          <Link
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
            href="/login"
          >
            Sign in
          </Link>
        }
        description="Sign in with a seeded demo account to continue."
        title="Authentication required"
      />
    );
  }

  if (!hasPermission(permission)) {
    return (
      <PermissionState
        action={
          <Link
            className="rounded-lg border bg-white px-4 py-2 text-sm font-semibold text-slate-800"
            href="/"
          >
            Return to overview
          </Link>
        }
        description={`Your ${roleLabel(user.role)} role does not include access to this area. The API will continue to enforce this restriction for direct requests.`}
      />
    );
  }

  return <>{children}</>;
}
