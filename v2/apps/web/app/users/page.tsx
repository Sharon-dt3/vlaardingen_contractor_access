"use client";

import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { PageHeader } from "@/components/ui/page-header";
import { UsersWorkspace } from "@/components/users/users-workspace";

// PUBLIC_INTERFACE
/**
 * Administrator-only screen for adding the people who can sign in.
 */
export default function UsersPage() {
  return (
    <PermissionBoundary permission="*">
      <div className="space-y-7">
        <PageHeader
          description="Add administrators and gate operators. Each person sets their own password."
          eyebrow="Administration"
          title="Users"
        />
        <UsersWorkspace />
      </div>
    </PermissionBoundary>
  );
}
