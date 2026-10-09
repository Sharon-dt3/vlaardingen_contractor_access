import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { InvitationWorkspace } from "@/components/workflows/invitation-workspace";

// PUBLIC_INTERFACE
/**
 * Hosts the role-aware Batch 2 invitation, registration, and evidence workflow.
 */
export default function InvitationsPage() {
  return (
    <PermissionBoundary permission="invitations:read">
      <InvitationWorkspace />
    </PermissionBoundary>
  );
}
