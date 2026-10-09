"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { ErrorState } from "@/components/states/content-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { LifeSavingHistoryItem, LifeSavingStatus } from "@/lib/domain";
import { formatDateTime, lifeSavingBadge } from "@/lib/domain";

type PersonLifeSaving = {
  person_id: string;
  status: LifeSavingStatus;
  history: LifeSavingHistoryItem[];
};

const METHOD_LABELS: Record<string, string> = {
  invitee_registration_link: "Confirmed by the contractor with their own registration link",
  seeded_demo: "Seeded demonstration record"
};

// PUBLIC_INTERFACE
/**
 * Shows the site whether a person confirmed the life-saving rules in force, when they
 * did so, and the exact wording they confirmed. Read-only: staff cannot confirm for them.
 */
export function LifeSavingRulesPanel({ personId }: { personId: string }) {
  const query = useQuery({
    queryKey: ["life-saving-rules", personId],
    queryFn: () => apiRequest<PersonLifeSaving>(`/api/people/${personId}/life-saving-rules`)
  });

  const badge = query.data ? lifeSavingBadge(query.data.status.status) : null;

  return (
    <section className="surface p-5" aria-labelledby="person-life-saving">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <h2 className="font-semibold text-slate-950" id="person-life-saving">
            Life-saving rules
          </h2>
        </div>
        {badge ? <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge> : null}
      </div>

      {query.isLoading ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
      ) : query.isError ? (
        <div className="mt-4">
          <ErrorState
            description={query.error instanceof ApiError ? query.error.message : undefined}
            onRetry={() => void query.refetch()}
          />
        </div>
      ) : query.data ? (
        <>
          <p className="mt-3 text-sm text-slate-700">
            {query.data.status.status === "confirmed"
              ? `Confirmed they read and understood version ${query.data.status.confirmed_rules_version} on ${formatDateTime(query.data.status.acknowledged_at ?? "")}. The gate lets them through on this check.`
              : query.data.status.status === "outdated"
                ? `Confirmed version ${query.data.status.confirmed_rules_version}, but version ${query.data.status.current_rules_version} is now in force. The gate refuses entry until they confirm the new version.`
                : "Has not confirmed the life-saving rules. The gate refuses entry until they do."}
          </p>

          {query.data.history.length > 0 ? (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Recorded confirmations
              </h3>
              <ul className="mt-2 space-y-3">
                {query.data.history.map((item) => (
                  <li className="rounded-xl border bg-slate-50/60 p-4" key={item.id}>
                    <p className="text-sm font-semibold text-slate-950">
                      Version {item.rules_version} · {formatDateTime(item.acknowledged_at)} ·{" "}
                      {item.language.toUpperCase()}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {METHOD_LABELS[item.method] ?? item.method}
                    </p>
                    <blockquote className="mt-2 border-l-4 border-emerald-600 pl-3 text-sm italic text-slate-700">
                      {item.statement_text}
                    </blockquote>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
