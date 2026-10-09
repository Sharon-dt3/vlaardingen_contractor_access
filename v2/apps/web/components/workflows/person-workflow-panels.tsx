"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileClock, Files } from "lucide-react";
import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState, ErrorState } from "@/components/states/content-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { apiBlobRequest, ApiError, apiRequest } from "@/lib/api-client";
import type {
  AuditEvent,
  Evidence,
  Invitation,
  TrainingResult,
  Visit
} from "@/lib/domain";
import { enumLabel, formatDateTime, statusTone } from "@/lib/domain";

function errorDescription(error: unknown): string | undefined {
  return error instanceof ApiError ? error.message : undefined;
}

// PUBLIC_INTERFACE
/**
 * Presents authorized evidence metadata and related lifecycle events for one person.
 */
export function PersonWorkflowPanels({ personId }: { personId: string }) {
  const { hasPermission } = useAuth();
  const canReadEvidence = hasPermission("evidence:read");
  const canReadAudit = hasPermission("audit:read");
  const canReadInvitations = hasPermission("invitations:read");
  const canReadTraining = hasPermission("training:read");
  const canReadVisits = hasPermission("visits:read");

  const evidenceQuery = useQuery({
    queryKey: ["workflows", "evidence", personId],
    queryFn: () => apiRequest<Evidence[]>(`/api/people/${personId}/evidence`),
    enabled: canReadEvidence,
    retry: false
  });
  const invitationsQuery = useQuery({
    queryKey: ["workflows", "invitations"],
    queryFn: () => apiRequest<Invitation[]>("/api/invitations"),
    enabled: canReadAudit && canReadInvitations,
    retry: false
  });
  const auditQuery = useQuery({
    queryKey: ["records", "audit-events"],
    queryFn: () => apiRequest<AuditEvent[]>("/api/audit/events"),
    enabled: canReadAudit,
    retry: false
  });
  const trainingQuery = useQuery({
    queryKey: ["batch3", "training-results", personId],
    queryFn: () =>
      apiRequest<TrainingResult[]>(`/api/people/${personId}/training-results`),
    enabled: canReadTraining,
    retry: false
  });
  const visitsQuery = useQuery({
    queryKey: ["records", "visits"],
    queryFn: () => apiRequest<Visit[]>("/api/visits"),
    enabled: canReadVisits,
    retry: false
  });

  const evidence = evidenceQuery.data ?? [];
  const visitIds = new Set(
    (visitsQuery.data ?? [])
      .filter((visit) => visit.person_id === personId)
      .map((visit) => visit.id)
  );
  const invitationIds = new Set(
    (invitationsQuery.data ?? [])
      .filter((invitation) => invitation.person_id === personId)
      .map((invitation) => invitation.id)
  );
  const evidenceIds = new Set(evidence.map((record) => record.id));
  const timeline = (auditQuery.data ?? []).filter((event) => {
    const eventPersonId =
      typeof event.details.person_id === "string"
        ? event.details.person_id
        : undefined;
    return (
      event.entity_id === personId ||
      eventPersonId === personId ||
      invitationIds.has(event.entity_id) ||
      evidenceIds.has(event.entity_id) ||
      visitIds.has(event.entity_id)
    );
  });

  async function downloadEvidence(record: Evidence) {
    const blob = await apiBlobRequest(`/api/evidence/${record.id}/content`);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = record.filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <section className="surface p-5" aria-labelledby="person-training">
        <div className="flex items-center gap-2">
          <FileClock className="h-5 w-5 text-emerald-700" aria-hidden="true" />
          <h2 className="font-semibold text-slate-950" id="person-training">
            Training history
          </h2>
        </div>
        {!canReadTraining ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Scored training history is not available to this role.
          </p>
        ) : trainingQuery.isError ? (
          <ErrorState
            className="mt-4 border-0 shadow-none"
            description={errorDescription(trainingQuery.error)}
            onRetry={() => void trainingQuery.refetch()}
          />
        ) : (trainingQuery.data ?? []).length === 0 ? (
          <EmptyState
            className="mt-4 border-0 py-8 shadow-none"
            description="Scored attempts, retry numbers, and expiry will appear after training is completed."
            title="No training attempts are linked"
          />
        ) : (
          <div className="mt-4 space-y-3">
            {(trainingQuery.data ?? []).map((result) => (
              <article className="rounded-xl border bg-slate-50/60 p-4" key={result.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">
                      Attempt {result.attempt_number} · {result.score}%
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Completed {formatDateTime(result.completed_at)}
                      {result.expires_at
                        ? ` · expires ${formatDateTime(result.expires_at)}`
                        : ""}
                    </p>
                  </div>
                  <StatusBadge tone={statusTone(result.outcome)}>
                    {enumLabel(result.outcome)}
                  </StatusBadge>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="surface p-5" aria-labelledby="person-evidence">
        <div className="flex items-center gap-2">
          <Files className="h-5 w-5 text-emerald-700" aria-hidden="true" />
          <h2 className="font-semibold text-slate-950" id="person-evidence">
            Evidence history
          </h2>
        </div>
        {!canReadEvidence ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Private evidence is not available to this role.
          </p>
        ) : evidenceQuery.isError ? (
          <ErrorState
            className="mt-4 border-0 shadow-none"
            description={errorDescription(evidenceQuery.error)}
            onRetry={() => void evidenceQuery.refetch()}
          />
        ) : evidence.length === 0 ? (
          <EmptyState
            className="mt-4 border-0 py-8 shadow-none"
            description="Evidence will appear after a registered invitation receives a document."
            title="No evidence is linked"
          />
        ) : (
          <div className="mt-4 space-y-3">
            {evidence.map((record) => (
              <article className="rounded-xl border bg-slate-50/60 p-4" key={record.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">
                      {enumLabel(record.evidence_type)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {record.expiry_date
                        ? `ID expiry date: ${record.expiry_date}${record.status === "verified" ? "" : " · Not verified"}`
                        : "No expiry date recorded"}
                    </p>
                  </div>
                  <StatusBadge tone={statusTone(record.status)}>
                    {enumLabel(record.status)}
                  </StatusBadge>
                </div>
                <button
                  className="mt-3 inline-flex items-center gap-2 text-xs font-semibold text-emerald-800 hover:text-emerald-950"
                  onClick={() => void downloadEvidence(record)}
                  type="button"
                >
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  Private preview / download
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="surface p-5" aria-labelledby="person-timeline">
        <div className="flex items-center gap-2">
          <FileClock className="h-5 w-5 text-emerald-700" aria-hidden="true" />
          <h2 className="font-semibold text-slate-950" id="person-timeline">
            Workflow timeline
          </h2>
        </div>
        {!canReadAudit ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Timeline audit evidence is not available to this role.
          </p>
        ) : auditQuery.isError ? (
          <ErrorState
            className="mt-4 border-0 shadow-none"
            description={errorDescription(auditQuery.error)}
            onRetry={() => void auditQuery.refetch()}
          />
        ) : timeline.length === 0 ? (
          <EmptyState
            className="mt-4 border-0 py-8 shadow-none"
            description="Invitation, training, compliance, approval, token, and evidence events will appear chronologically."
            title="No workflow events are linked"
          />
        ) : (
          <ol className="mt-5 space-y-4 border-l border-slate-200 pl-5">
            {timeline.map((event) => (
              <li className="relative" key={event.id}>
                <span className="absolute -left-[1.55rem] top-1.5 h-2 w-2 rounded-full bg-emerald-600 ring-4 ring-white" />
                <p className="text-sm font-semibold text-slate-950">
                  {enumLabel(event.action.replace(/\./g, "_"))}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {event.reason}
                </p>
                <time className="mt-1 block text-xs text-slate-500">
                  {formatDateTime(event.occurred_at)}
                </time>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
