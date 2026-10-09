"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, CalendarDays, Mail, UserRound } from "lucide-react";
import Link from "next/link";
import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { EmptyState, ErrorState } from "@/components/states/content-state";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { LifeSavingRulesPanel } from "@/components/workflows/life-saving-rules-panel";
import { PersonWorkflowPanels } from "@/components/workflows/person-workflow-panels";
import { apiRequest, ApiError } from "@/lib/api-client";
import type { Company, Person, Visit } from "@/lib/domain";
import {
  enumLabel,
  formatDateTime,
  statusTone
} from "@/lib/domain";

type PersonDetailPageProps = {
  params: {
    personId: string;
  };
};

// PUBLIC_INTERFACE
/**
 * Presents one synthetic person's core profile and foundational visits.
 */
export default function PersonDetailPage({ params }: PersonDetailPageProps) {
  return (
    <PermissionBoundary permission="people:read">
      <PersonDetail personId={params.personId} />
    </PermissionBoundary>
  );
}

function PersonDetail({ personId }: { personId: string }) {
  const peopleQuery = useQuery({
    queryKey: ["records", "people"],
    queryFn: () => apiRequest<Person[]>("/api/people")
  });
  const companiesQuery = useQuery({
    queryKey: ["records", "companies"],
    queryFn: () => apiRequest<Company[]>("/api/companies"),
    retry: false
  });
  const visitsQuery = useQuery({
    queryKey: ["records", "visits"],
    queryFn: () => apiRequest<Visit[]>("/api/visits"),
    retry: false
  });

  if (peopleQuery.isLoading) {
    return <PageSkeleton />;
  }

  if (peopleQuery.isError) {
    return (
      <ErrorState
        description={
          peopleQuery.error instanceof ApiError
            ? peopleQuery.error.message
            : undefined
        }
        onRetry={() => void peopleQuery.refetch()}
      />
    );
  }

  const person = peopleQuery.data?.find((candidate) => candidate.id === personId);
  if (!person) {
    return (
      <EmptyState
        action={
          <Link
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
            href="/people"
          >
            Return to people
          </Link>
        }
        description="The requested identifier is not present in the authorized Batch 1 records."
        title="Person not found"
      />
    );
  }

  const company = companiesQuery.data?.find(
    (candidate) => candidate.id === person.company_id
  );
  const visits = visitsQuery.data?.filter(
    (candidate) => candidate.person_id === person.id
  );

  return (
    <div className="space-y-7">
      <PageHeader
        actions={
          <Link
            className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm font-semibold text-slate-700"
            href="/people"
          >
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            All people
          </Link>
        }
        badge={
          <StatusBadge tone={statusTone(person.standing)}>
            {enumLabel(person.standing)}
          </StatusBadge>
        }
        description="Authorized synthetic profile with linked visits, private evidence metadata, and chronological workflow context."
        eyebrow={enumLabel(person.population)}
        title={`${person.first_name} ${person.last_name}`}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <article className="surface p-5">
          <UserRound aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Seed reference
          </p>
          <p className="mt-1 font-mono text-sm text-slate-900">{person.seed_key}</p>
        </article>
        <article className="surface p-5">
          <Mail aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Contact
          </p>
          <p className="mt-1 break-all text-sm font-semibold text-slate-900">
            {person.email}
          </p>
        </article>
        <article className="surface p-5">
          <Building2 aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Company
          </p>
          <p className="mt-1 text-sm font-semibold text-slate-900">
            {company?.name ?? `${person.company_id.slice(0, 8)}…`}
          </p>
        </article>
      </div>

      <section className="surface p-5" aria-labelledby="person-visits">
        <div className="flex items-center gap-2">
          <CalendarDays aria-hidden="true" className="h-5 w-5 text-emerald-700" />
          <h2 className="font-semibold text-slate-950" id="person-visits">
            Foundational visits
          </h2>
        </div>
        {visitsQuery.isError ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Visit details are not available to this role.
          </p>
        ) : visits && visits.length > 0 ? (
          <div className="mt-4 grid gap-3">
            {visits.map((visit) => (
              <article
                className="flex flex-col gap-3 rounded-xl border bg-slate-50/60 p-4 sm:flex-row sm:items-center sm:justify-between"
                key={visit.id}
              >
                <div>
                  <p className="text-sm font-semibold text-slate-950">{visit.purpose}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {formatDateTime(visit.starts_at)} – {formatDateTime(visit.ends_at)}
                  </p>
                </div>
                <StatusBadge tone={statusTone(visit.status)}>
                  {enumLabel(visit.status)}
                </StatusBadge>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            No foundational visits are linked to this person.
          </p>
        )}
      </section>

      <LifeSavingRulesPanel personId={person.id} />

      <PersonWorkflowPanels personId={person.id} />
    </div>
  );
}
