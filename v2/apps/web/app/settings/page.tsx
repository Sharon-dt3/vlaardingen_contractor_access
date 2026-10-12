"use client";

import { KeyRound, Server, ShieldCheck } from "lucide-react";
import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { useAuth } from "@/components/auth/auth-provider";
import { SiteAccessSettings } from "@/components/settings/site-access-settings";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { getApiBaseUrl } from "@/lib/api-client";
import { roleLabel } from "@/lib/domain";

// PUBLIC_INTERFACE
/**
 * Presents administrator-only local demo and session configuration details.
 */
export default function SettingsPage() {
  return (
    <PermissionBoundary permission="*">
      <SettingsContent />
    </PermissionBoundary>
  );
}

function SettingsContent() {
  const { user } = useAuth();

  return (
    <div className="space-y-7">
      <PageHeader
        description="Set how long access lasts at each site and review your account's access."
        eyebrow="Administration"
        title="Settings"
      />
      <div className="grid gap-4 md:grid-cols-3">
        <article className="surface p-5">
          <ShieldCheck aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <h2 className="mt-4 text-sm font-semibold text-slate-950">Session role</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {user ? roleLabel(user.role) : "Unavailable"}
          </p>
        </article>
        <article className="surface p-5">
          <Server aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <h2 className="mt-4 text-sm font-semibold text-slate-950">API origin</h2>
          <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
            {getApiBaseUrl()}
          </p>
        </article>
        <article className="surface p-5">
          <KeyRound aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <h2 className="mt-4 text-sm font-semibold text-slate-950">
            Security boundary
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Signed HttpOnly cookie with API-enforced permissions.
          </p>
        </article>
      </div>
      <SiteAccessSettings />
      <section className="surface p-5">
        <h2 className="text-base font-semibold text-slate-950">
          Effective permissions
        </h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {user?.permissions.map((permission) => (
            <StatusBadge key={permission} tone="neutral">
              {permission === "*" ? "All permissions" : permission}
            </StatusBadge>
          ))}
        </div>
      </section>
    </div>
  );
}
