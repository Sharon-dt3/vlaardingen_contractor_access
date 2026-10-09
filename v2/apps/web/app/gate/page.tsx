"use client";

import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { GateOperatorKiosk } from "@/components/workflows/gate-operator-kiosk";

// PUBLIC_INTERFACE
/**
 * Presents the server-authoritative Batch 4 gate evaluation kiosk to accounts
 * permitted to submit gate evaluation commands.
 */
export default function GatePage() {
  return (
    <PermissionBoundary permission="gate:evaluate">
      <GateOperatorKiosk />
    </PermissionBoundary>
  );
}
