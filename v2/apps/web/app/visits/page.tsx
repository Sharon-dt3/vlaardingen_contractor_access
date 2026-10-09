"use client";

import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { Batch3Workspace } from "@/components/workflows/batch3-workspace";

// PUBLIC_INTERFACE
/**
 * Presents authorized visit records through the Batch 3 training, compliance,
 * approval, blacklist, and access-token workflow workspace.
 */
export default function VisitsPage() {
  return (
    <PermissionBoundary permission="visits:read">
      <Batch3Workspace />
    </PermissionBoundary>
  );
}
