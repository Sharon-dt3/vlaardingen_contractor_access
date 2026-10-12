"use client";

import {
  Building2,
  ClipboardList,
  FileClock,
  ScanLine,
  Settings,
  ShieldCheck,
  UsersRound
} from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/states/content-state";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { ExpiryRevalidationWorkspace } from "@/components/workflows/expiry-revalidation-workspace";
import { OperationalDashboard } from "@/components/workflows/operational-dashboard";
import { roleLabel } from "@/lib/domain";

const modules = [
  {
    label: "People",
    description: "Review synthetic person standing and open individual records.",
    href: "/people",
    permission: "people:read",
    icon: UsersRound
  },
  {
    label: "Companies",
    description: "Browse the fictional organizations in the deterministic seed.",
    href: "/companies",
    permission: "companies:read",
    icon: Building2
  },
  {
    label: "Visits",
    description: "Inspect planned and current visit records for Vlaardingen.",
    href: "/visits",
    permission: "visits:read",
    icon: ClipboardList
  },
  {
    label: "Gate kiosk",
    description:
      "Scan an opaque token, then use Verify to privately upload a Dutch ID or driving licence before requesting the server gate decision.",
    href: "/gate",
    permission: "gate:evaluate",
    icon: ScanLine
  },
  {
    label: "Audit trail",
    description: "Read chronological, append-only lifecycle evidence.",
    href: "/audit",
    permission: "audit:read",
    icon: FileClock
  },
  {
    label: "Settings",
    description: "Review administrator-only demo and session configuration.",
    href: "/settings",
    permission: "*",
    icon: Settings
  }
] as const;

// PUBLIC_INTERFACE
/**
 * Presents modules derived from the authenticated user's API permissions.
 */
export default function HomePage() {
  const { user, hasPermission } = useAuth();
  const visibleModules = modules.filter((module) => hasPermission(module.permission));

  return (
    <div className="space-y-8">
      <PageHeader
        badge={<StatusBadge tone="success">Signed in</StatusBadge>}
        title={user ? `Welcome, ${user.display_name}` : "Welcome"}
      />

      {user ? (
        <section className="relative overflow-hidden rounded-2xl bg-slate-950 px-6 py-7 text-white shadow-soft sm:px-8">
          <div className="absolute -right-20 -top-20 h-56 w-56 rounded-full bg-emerald-400/15 blur-3xl" />
          <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
                <ShieldCheck aria-hidden="true" className="h-5 w-5" />
                Authorized session
              </div>
              <h2 className="mt-3 text-2xl font-semibold">{roleLabel(user.role)}</h2>
              <p className="mt-2 text-sm text-slate-300">
                Account <span className="font-semibold text-white">{user.handle}</span> ·{" "}
                {user.permissions.includes("*")
                  ? "All API permissions"
                  : `${user.permissions.length} API permissions`}
              </p>
            </div>
          </div>
        </section>
      ) : null}

      {hasPermission("dashboard:read") ? <OperationalDashboard /> : null}

      {hasPermission("expiry:read") ? <ExpiryRevalidationWorkspace /> : null}

      {visibleModules.length > 0 ? (
        <section aria-labelledby="authorized-modules">
          <div className="mb-4">
            <h2 className="text-base font-semibold text-slate-950" id="authorized-modules">
              Authorized modules
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Only modules supported by your current permissions are shown.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visibleModules.map((module) => {
              const Icon = module.icon;
              return (
                <Link
                  className="surface group p-5 transition hover:-translate-y-0.5 hover:border-emerald-300 hover:shadow-lg"
                  href={module.href}
                  key={module.href}
                >
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
                    <Icon aria-hidden="true" className="h-5 w-5" />
                  </span>
                  <h3 className="mt-4 text-sm font-semibold text-slate-950">
                    {module.label}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {module.description}
                  </p>
                </Link>
              );
            })}
          </div>
        </section>
      ) : (
        <EmptyState
          description="This participant account has no Batch 1 record-read permissions. Later workflow batches will add the participant's own registration, evidence, training, and token workspace."
          title="Your personal workspace arrives in a later batch"
        />
      )}
    </div>
  );
}
