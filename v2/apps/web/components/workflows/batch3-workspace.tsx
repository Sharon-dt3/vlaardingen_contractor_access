"use client";

import { isoToSiteInput, siteInputToIso, yourClockHint } from "@/lib/time";
import {
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ClipboardCheck,
  KeyRound,
  Printer,
  ShieldAlert,
  ShieldCheck,
  XCircle
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import {
  EmptyState,
  ErrorState,
  PermissionState
} from "@/components/states/content-state";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import type {
  AccessToken,
  Approval,
  BlacklistEntry,
  BlacklistSubjectType,
  Company,
  ComplianceCheck,
  ComplianceEvaluation,
  DemoClock,
  Evidence,
  Invitation,
  Person,
  TokenIssueResponse,
  TrainingModule,
  TrainingResult,
  Visit
} from "@/lib/domain";
import {
  enumLabel,
  formatDateTime,
  formatInSiteZone,
  statusTone
} from "@/lib/domain";

const fieldClass =
  "mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-emerald-600";
const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-600";
const primaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
const dangerButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50";

type PersonDeletionResult = {
  person_id: string;
  shared_objects_retained: number;
  storage_objects_not_erased: number;
  limitations: string[];
};

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof ApiError ? error.message : "The action could not be completed.";
}

function FormError({ error }: { error: unknown }) {
  const message = errorMessage(error);
  return message ? (
    <p
      aria-live="assertive"
      className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      {message}
    </p>
  ) : null;
}

function complianceTone(status: ComplianceCheck["status"]): StatusTone {
  if (status === "passed") {
    return "success";
  }
  if (status === "missing" || status === "expired") {
    return "warning";
  }
  if (status === "blocked" || status === "failed") {
    return "danger";
  }
  return "neutral";
}

function invalidateBatch3Queries(
  queryClient: ReturnType<typeof useQueryClient>,
  personId?: string,
  visitId?: string
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["records", "audit-events"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "visits"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "people"] }),
    queryClient.invalidateQueries({ queryKey: ["batch3", "blacklist"] }),
    ...(personId
      ? [
          queryClient.invalidateQueries({
            queryKey: ["batch3", "training-results", personId]
          })
        ]
      : []),
    ...(visitId
      ? [
          queryClient.invalidateQueries({
            queryKey: ["batch3", "compliance", visitId]
          }),
          queryClient.invalidateQueries({
            queryKey: ["batch3", "tokens", visitId]
          })
        ]
      : [])
  ]);
}

// PUBLIC_INTERFACE
/**
 * Coordinates the Batch 3 training, compliance, approval, blacklist, and
 * access-token workflows. All eligibility and authorization decisions remain
 * owned by the API; this component only displays typed server outcomes.
 */
export function Batch3Workspace() {
  const { hasPermission, user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedVisitId, setSelectedVisitId] = useState("");
  const [personToDelete, setPersonToDelete] = useState<Person | null>(null);
  const [confirmationId, setConfirmationId] = useState("");
  const [deletedPersonName, setDeletedPersonName] = useState("");
  const [deletionResult, setDeletionResult] = useState<PersonDeletionResult | null>(null);
  const canDeletePeople = user?.role === "system_admin" && hasPermission("people:delete");
  const deletePersonMutation = useMutation({
    mutationFn: (target: Person) =>
      apiRequest<PersonDeletionResult>(`/api/people/${target.id}`, {
        method: "DELETE",
        body: { person_id: target.id, confirmation: "DELETE PERSON" }
      }),
    onSuccess: async (result, target) => {
      setDeletedPersonName(`${target.first_name} ${target.last_name}`);
      setDeletionResult(result);
      setSelectedVisitId("");
      setPersonToDelete(null);
      setConfirmationId("");
      // Remove detail data before the selector can switch to another visit.
      queryClient.removeQueries({ queryKey: ["batch3", "training-results", target.id] });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records"] }),
        queryClient.invalidateQueries({ queryKey: ["workflows"] }),
        queryClient.invalidateQueries({ queryKey: ["batch3"] }),
        queryClient.invalidateQueries({ queryKey: ["batch6"] })
      ]);
    }
  });
  const visitsQuery = useQuery({
    queryKey: ["records", "visits"],
    queryFn: () => apiRequest<Visit[]>("/api/visits"),
    retry: false
  });
  const peopleQuery = useQuery({
    queryKey: ["records", "people"],
    queryFn: () => apiRequest<Person[]>("/api/people"),
    retry: false
  });
  const invitationsQuery = useQuery({
    queryKey: ["workflows", "invitations"],
    queryFn: () => apiRequest<Invitation[]>("/api/invitations"),
    enabled: hasPermission("invitations:read") && hasPermission("evidence:read"),
    retry: false
  });
  const evidenceLinksQuery = useQuery({
    queryKey: ["batch3", "evidence-links", invitationsQuery.data?.map((item) => `${item.id}:${item.person_id}`)],
    queryFn: async () => {
      const ids = Array.from(new Set(
        (invitationsQuery.data ?? [])
          .map((item) => item.person_id)
          .filter((id): id is string => Boolean(id))
      ));
      const results = await Promise.all(ids.map(
        (id) => apiRequest<Evidence[]>(`/api/people/${id}/evidence`)
      ));
      // Upload alone is not enough; only an authorized review marks evidence verified.
      return new Set(results.flat().filter((item) =>
        item.invitation_id && item.status === "verified"
      ).map((item) => item.invitation_id as string));
    },
    enabled: hasPermission("evidence:read") && invitationsQuery.isSuccess,
    retry: false
  });
  const companiesQuery = useQuery({
    queryKey: ["records", "companies"],
    queryFn: () => apiRequest<Company[]>("/api/companies"),
    enabled: hasPermission("companies:read"),
    retry: false
  });

  useEffect(() => {
    // Never retain a visit after its invitation evidence is no longer verified.
    if (!evidenceLinksQuery.isSuccess || !invitationsQuery.isSuccess) {
      return;
    }
    const eligibleVisits = (visitsQuery.data ?? []).filter((visit) =>
      invitationsQuery.data.some((invitation) =>
        invitation.visit_id === visit.id &&
        invitation.person_id === visit.person_id &&
        evidenceLinksQuery.data.has(invitation.id)
      )
    );
    if (!eligibleVisits.some((visit) => visit.id === selectedVisitId)) {
      setSelectedVisitId(eligibleVisits[0]?.id ?? "");
    }
  }, [selectedVisitId, visitsQuery.data, invitationsQuery.data, invitationsQuery.isSuccess, evidenceLinksQuery.data, evidenceLinksQuery.isSuccess]);

  if (visitsQuery.isLoading || peopleQuery.isLoading || invitationsQuery.isLoading || evidenceLinksQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (
    [visitsQuery.error, invitationsQuery.error, evidenceLinksQuery.error].some(
      (error) => error instanceof ApiError && error.status === 403
    )
  ) {
    return <PermissionState description="Invitation evidence is not available to this role." />;
  }
  if (visitsQuery.isError || peopleQuery.isError || invitationsQuery.isError || evidenceLinksQuery.isError) {
    const error = visitsQuery.error ?? peopleQuery.error ?? invitationsQuery.error ?? evidenceLinksQuery.error;
    return (
      <ErrorState
        description={errorMessage(error) ?? undefined}
        onRetry={() => {
          void visitsQuery.refetch();
          void peopleQuery.refetch();
          if (hasPermission("invitations:read") && hasPermission("evidence:read")) {
            void invitationsQuery.refetch();
            void evidenceLinksQuery.refetch();
          }
        }}
      />
    );
  }

  const visits = visitsQuery.data ?? [];
  const verifiedVisits = visits.filter((visit) =>
    (invitationsQuery.data ?? []).some((invitation) =>
      invitation.visit_id === visit.id &&
      invitation.person_id === visit.person_id &&
      evidenceLinksQuery.data?.has(invitation.id)
    )
  );
  const selectedVisit = verifiedVisits.find((visit) => visit.id === selectedVisitId);
  const person = peopleQuery.data?.find(
    (candidate) => candidate.id === selectedVisit?.person_id
  );
  const company = companiesQuery.data?.find(
    (candidate) => candidate.id === person?.company_id
  );

  return (
    <div className="space-y-7">
      <PageHeader
        badge={<StatusBadge tone="demo">Server-authoritative</StatusBadge>}
        description="Confirm completed training, inspect every compliance check, record auditable approval decisions, and issue opaque visit-bound access tokens. The API remains the source of truth for every outcome."
        eyebrow="Steps 4–6"
        title="Training, approval & access workspace"
      />

      <section className="surface p-5" aria-labelledby="batch3-visit-selection">
        <label className={labelClass} htmlFor="batch3-visit-selection">
          Person with verified invitation evidence
        </label>
        <select
          className={fieldClass}
          id="batch3-visit-selection"
          onChange={(event) => setSelectedVisitId(event.target.value)}
          value={selectedVisit?.id ?? ""}
        >
          <option value="">Select a person</option>
          {verifiedVisits.map((visit) => {
            const visitPerson = peopleQuery.data?.find(
              (candidate) => candidate.id === visit.person_id
            );
            return (
              <option key={visit.id} value={visit.id}>
                {visitPerson?.first_name ?? "Person"}{" "}
                {visitPerson?.last_name ?? visit.person_id.slice(0, 8)}
                {" · "}{visit.purpose}
              </option>
            );
          })}
        </select>
        {canDeletePeople && verifiedVisits.length > 0 ? (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Delete is permanent and removes all data linked to the person, not just this visit.
            </p>
            <ul className="max-h-48 space-y-2 overflow-y-auto" aria-label="People available for deletion">
              {Array.from(new Set(verifiedVisits.map((visit) => visit.person_id))).map((personId) => {
                const candidate = peopleQuery.data?.find((item) => item.id === personId);
                if (!candidate) {
                  return null;
                }
                return (
                  <li className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2" key={personId}>
                    <span className="min-w-0 text-sm text-slate-800">
                      {candidate.first_name} {candidate.last_name}
                      <span className="ml-2 text-xs text-muted-foreground">{candidate.email}</span>
                    </span>
                    <button
                      className={dangerButton}
                      disabled={deletePersonMutation.isPending}
                      onClick={() => {
                        deletePersonMutation.reset();
                        setDeletedPersonName("");
                        setDeletionResult(null);
                        setConfirmationId("");
                        setPersonToDelete(candidate);
                      }}
                      type="button"
                      aria-label={`Delete ${candidate.first_name} ${candidate.last_name} (${candidate.email})`}
                    >
                      Delete
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
        {canDeletePeople && personToDelete ? (
          <div className="mt-4 space-y-3 rounded-lg border border-red-300 bg-red-50 p-4" role="group" aria-label="Confirm permanent person deletion">
            <p className="font-semibold text-red-900">Permanently delete this person and all linked data?</p>
            <p className="text-sm text-red-900">
              {personToDelete.first_name} {personToDelete.last_name} · {personToDelete.email}
            </p>
            <p className="break-all font-mono text-xs text-red-900">{personToDelete.id}</p>
            <label className="block text-sm font-medium text-red-900" htmlFor="batch3-delete-confirmation">
              Type the exact UUID shown above to confirm this person&apos;s identity
            </label>
            <input
              autoComplete="off"
              className={fieldClass}
              disabled={deletePersonMutation.isPending}
              id="batch3-delete-confirmation"
              onChange={(event) => setConfirmationId(event.target.value)}
              value={confirmationId}
            />
            <div className="flex flex-wrap gap-2">
              <button
                className={dangerButton}
                disabled={deletePersonMutation.isPending || confirmationId !== personToDelete.id}
                onClick={() => {
                  if (canDeletePeople && personToDelete && confirmationId === personToDelete.id) {
                    deletePersonMutation.mutate(personToDelete);
                  }
                }}
                type="button"
              >
                {deletePersonMutation.isPending ? "Deleting…" : "Permanently delete person"}
              </button>
              <button
                className={secondaryButton}
                disabled={deletePersonMutation.isPending}
                onClick={() => {
                  setPersonToDelete(null);
                  setConfirmationId("");
                  deletePersonMutation.reset();
                }}
                type="button"
              >
                Cancel
              </button>
            </div>
            <FormError error={deletePersonMutation.error} />
          </div>
        ) : null}
        {deletedPersonName ? (
          <div className="mt-3 text-sm text-slate-800" role="status">
            <p>{deletedPersonName}&apos;s database records were deleted. The lists have been refreshed.</p>
            {deletionResult ? (
              <p className="mt-1 text-amber-900">
                {deletionResult.shared_objects_retained} shared private object(s) retained;{" "}
                {deletionResult.storage_objects_not_erased} private object(s) could not be erased.{" "}
                {deletionResult.limitations.filter(Boolean).join(" ")}
              </p>
            ) : null}
          </div>
        ) : null}
        {verifiedVisits.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            No verified invitation evidence is linked to an authorized visit.
          </p>
        ) : null}
      </section>

      {!selectedVisit || !person ? (
        <EmptyState
          description="Select a visit that is visible to your current role to inspect its Batch 3 progression."
          title="Select an authorized visit"
        />
      ) : (
        <>
          <VisitSummary person={person} visit={selectedVisit} />
          <Batch3Progress personId={person.id} visitId={selectedVisit.id} />
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <TrainingPanel person={person} visitId={selectedVisit.id} />
            <ComplianceApprovalPanel person={person} visit={selectedVisit} />
          </div>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <BlacklistPanel company={company} person={person} />
            <AccessTokenPanel key={selectedVisit.id} visit={selectedVisit} />
          </div>
        </>
      )}
    </div>
  );
}

function VisitSummary({ person, visit }: { person: Person; visit: Visit }) {
  return (
    <section className="surface p-5" aria-labelledby="selected-visit-summary">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="eyebrow">{enumLabel(person.population)}</p>
          <h2 className="mt-2 text-lg font-semibold text-slate-950" id="selected-visit-summary">
            {person.first_name} {person.last_name}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{visit.purpose}</p>
        </div>
        <StatusBadge tone={statusTone(visit.status)}>
          {enumLabel(visit.status)}
        </StatusBadge>
      </div>
      <dl className="mt-5 grid gap-4 border-t pt-4 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Visit starts
          </dt>
          <dd className="mt-1 text-slate-900">{formatDateTime(visit.starts_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Visit ends
          </dt>
          <dd className="mt-1 text-slate-900">{formatDateTime(visit.ends_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Person standing
          </dt>
          <dd className="mt-1">
            <StatusBadge tone={statusTone(person.standing)}>
              {enumLabel(person.standing)}
            </StatusBadge>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Batch3Progress({ personId, visitId }: { personId: string; visitId: string }) {
  const { hasPermission } = useAuth();
  const trainingQuery = useQuery({
    queryKey: ["batch3", "training-results", personId],
    queryFn: () =>
      apiRequest<TrainingResult[]>(`/api/people/${personId}/training-results`),
    enabled: hasPermission("training:read"),
    retry: false
  });
  const complianceQuery = useQuery({
    queryKey: ["batch3", "compliance", visitId],
    queryFn: () =>
      apiRequest<ComplianceEvaluation>(`/api/visits/${visitId}/compliance`),
    enabled: hasPermission("compliance:read"),
    retry: false
  });
  const tokensQuery = useQuery({
    queryKey: ["batch3", "tokens", visitId],
    queryFn: () => apiRequest<AccessToken[]>(`/api/visits/${visitId}/tokens`),
    enabled: hasPermission("tokens:read"),
    retry: false
  });

  // Compliance is the server's effective-clock assessment; never compare
  // training expiry with the browser clock to imply access eligibility.
  const passedTraining = (trainingQuery.data ?? []).some(
    (result) => result.outcome === "passed"
  );
  const tokenActive = (tokensQuery.data ?? []).some(
    (token) => token.status === "active"
  );
  const steps = [
    {
      label: "Scored training",
      detail: passedTraining ? "Passing result recorded; check compliance for current eligibility" : "Passing result pending",
      complete: passedTraining,
      restricted: !hasPermission("training:read")
    },
    {
      label: "Compliance",
      detail: complianceQuery.data
        ? complianceQuery.data.eligible
          ? "Current checks pass"
          : "Blocking checks need action"
        : "Evaluate current checks",
      complete: Boolean(complianceQuery.data?.eligible),
      restricted: !hasPermission("compliance:read")
    },
    {
      label: "Access token",
      detail: tokenActive ? "Active QR token issued" : "Approved eligible visit required",
      complete: tokenActive,
      restricted: !hasPermission("tokens:read")
    }
  ];

  return (
    <ol className="grid gap-3 sm:grid-cols-3" aria-label="Batch 3 workflow progress">
      {steps.map((step, index) => (
        <li className="surface flex items-center gap-3 p-4" key={step.label}>
          <span
            className={`grid h-8 w-8 place-items-center rounded-full text-sm font-bold ${
              step.complete
                ? "bg-emerald-100 text-emerald-800"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {step.complete ? <CheckCircle2 aria-hidden="true" className="h-4 w-4" /> : index + 4}
          </span>
          <div>
            <p className="text-xs text-muted-foreground">Step {index + 4}</p>
            <p className="text-sm font-semibold text-slate-950">{step.label}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {step.restricted ? "Restricted for this role" : step.detail}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function TrainingPanel({
  person,
  visitId
}: {
  person: Person;
  visitId: string;
}) {
  const { hasPermission, user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedModuleId, setSelectedModuleId] = useState("");
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [sheqBasics, setSheqBasics] = useState(false);
  const [vlaardingenSiteRules, setVlaardingenSiteRules] = useState(false);
  const canRead = hasPermission("training:read");
  const canComplete = hasPermission("training:complete");
  const isAdmin = user?.role === "system_admin";
  const modulesQuery = useQuery({
    queryKey: ["batch3", "training-modules"],
    queryFn: () => apiRequest<TrainingModule[]>("/api/training/modules"),
    enabled: canRead,
    retry: false
  });
  const resultsQuery = useQuery({
    queryKey: ["batch3", "training-results", person.id],
    queryFn: () =>
      apiRequest<TrainingResult[]>(`/api/people/${person.id}/training-results`),
    enabled: canRead,
    retry: false
  });

  useEffect(() => {
    if (!selectedModuleId && modulesQuery.data?.[0]) {
      setSelectedModuleId(modulesQuery.data[0].id);
    }
  }, [modulesQuery.data, selectedModuleId]);

  const trainingModule = modulesQuery.data?.find(
    (candidate) => candidate.id === selectedModuleId
  );
  const attemptMutation = useMutation({
    mutationFn: () => {
      if (!trainingModule) {
        throw new Error("Select an active training module.");
      }
      return apiRequest<TrainingResult>(
        `/api/people/${person.id}/training-modules/${trainingModule.id}/attempts`,
        { method: "POST", body: { answers } }
      );
    },
    onSuccess: async () => {
      setAnswers({});
      // Training results determine visit compliance, so refresh both scopes.
      await invalidateBatch3Queries(queryClient, person.id, visitId);
    }
  });
  const completionMutation = useMutation({
    mutationFn: () =>
      apiRequest<TrainingResult[]>(
        `/api/people/${person.id}/training-completion`,
        {
          method: "POST",
          body: {
            sheq_basics: sheqBasics,
            vlaardingen_site_rules: vlaardingenSiteRules
          }
        }
      ),
    onSuccess: async () => {
      setSheqBasics(false);
      setVlaardingenSiteRules(false);
      // Both confirmed results affect the current visit's server-side checks.
      await invalidateBatch3Queries(queryClient, person.id, visitId);
    }
  });

  if (!canRead) {
    return (
      <section className="surface p-5">
        <PermissionState
          className="border-0 py-6 shadow-none"
          description="Training records are not available to this role."
          title="Training is restricted"
        />
      </section>
    );
  }
  if (modulesQuery.isLoading || resultsQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (modulesQuery.isError || resultsQuery.isError) {
    const error = modulesQuery.error ?? resultsQuery.error;
    return (
      <ErrorState
        description={errorMessage(error) ?? undefined}
        onRetry={() => {
          void modulesQuery.refetch();
          void resultsQuery.refetch();
        }}
      />
    );
  }

  const results = resultsQuery.data ?? [];
  return (
    <section className="surface p-5" aria-labelledby="training-workspace">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
          <ClipboardCheck aria-hidden="true" className="h-5 w-5" />
        </span>
        <div>
          <h2 className="font-semibold text-slate-950" id="training-workspace">
            Scored training
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {isAdmin
              ? "Confirm both completed trainings for this person. Results and expiry are recorded by the API."
              : "Scores, retries, outcomes, and expiry are calculated and persisted by the API."}
          </p>
        </div>
      </div>

      {isAdmin ? (
        <form
          className="mt-5 space-y-4 border-t pt-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (sheqBasics && vlaardingenSiteRules && !completionMutation.isPending) {
              completionMutation.mutate();
            }
          }}
        >
          <p className="text-sm text-slate-700">
            As an administrator, confirm training you know this person has completed.
            Both confirmations are required before submitting.
          </p>
          <fieldset className="space-y-2">
            <legend className="text-sm font-semibold text-slate-950">
              Training completed
            </legend>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border bg-white px-3 py-3 text-sm text-slate-700">
              <input
                checked={sheqBasics}
                disabled={!canComplete || completionMutation.isPending}
                onChange={(event) => setSheqBasics(event.target.checked)}
                type="checkbox"
              />
              SHEQ Basics
            </label>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border bg-white px-3 py-3 text-sm text-slate-700">
              <input
                checked={vlaardingenSiteRules}
                disabled={!canComplete || completionMutation.isPending}
                onChange={(event) => setVlaardingenSiteRules(event.target.checked)}
                type="checkbox"
              />
              Vlaardingen Site Rules
            </label>
          </fieldset>
          {canComplete ? (
            <>
              <FormError error={completionMutation.error} />
              <button
                className={primaryButton}
                disabled={!sheqBasics || !vlaardingenSiteRules || completionMutation.isPending}
                type="submit"
              >
                {completionMutation.isPending ? "Submitting…" : "Submit"}
              </button>
            </>
          ) : (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              This role can read results but cannot submit training for this person.
            </p>
          )}
        </form>
      ) : (
      <div className="mt-5 grid gap-4 border-t pt-5">
        <label className={labelClass}>
          Training module
          <select
            className={fieldClass}
            onChange={(event) => {
              setSelectedModuleId(event.target.value);
              setAnswers({});
            }}
            value={selectedModuleId}
          >
            {(modulesQuery.data ?? [])
              .filter((candidate) => candidate.is_active)
              .map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name} · {candidate.passing_score}% required
                </option>
              ))}
          </select>
        </label>

        {trainingModule ? (
          <form
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault();
              attemptMutation.mutate();
            }}
          >
            <div className="rounded-xl bg-slate-50 p-4 text-xs text-slate-600">
              <strong className="text-slate-800">{trainingModule.code}</strong> · {trainingModule.language} · valid for{" "}
              {trainingModule.validity_days} days. Choose one answer for every question.
            </div>
            {trainingModule.questions.map((question, questionIndex) => (
              <fieldset className="rounded-xl border p-4" key={question.id}>
                <legend className="px-1 text-sm font-semibold text-slate-950">
                  {questionIndex + 1}. {question.prompt}
                </legend>
                <div className="mt-3 grid gap-2">
                  {question.options.map((option, optionIndex) => (
                    <label
                      className="flex cursor-pointer items-start gap-3 rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
                      key={`${question.id}-${optionIndex}`}
                    >
                      <input
                        checked={answers[question.id] === optionIndex}
                        className="mt-0.5"
                        name={question.id}
                        onChange={() =>
                          setAnswers((current) => ({
                            ...current,
                            [question.id]: optionIndex
                          }))
                        }
                        required
                        type="radio"
                      />
                      <span>{option}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            {canComplete ? (
              <>
                <FormError error={attemptMutation.error} />
                <button
                  className={primaryButton}
                  disabled={
                    attemptMutation.isPending ||
                    Object.keys(answers).length !== trainingModule.questions.length
                  }
                  type="submit"
                >
                  {attemptMutation.isPending ? "Submitting scored attempt…" : "Submit scored attempt"}
                </button>
              </>
            ) : (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                This role can read results but cannot submit training for this person.
              </p>
            )}
          </form>
        ) : (
          <EmptyState
            className="border-0 py-6 shadow-none"
            description="There are no active training modules visible to this role."
            title="No active training modules"
          />
        )}
      </div>
      )}

      <div className="mt-6 border-t pt-5">
        <h3 className="text-sm font-semibold text-slate-950">Training history</h3>
        {results.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No training results have been recorded for this person.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {results.map((result) => (
              <article
                className="flex flex-col gap-2 rounded-xl border bg-slate-50/60 p-3 sm:flex-row sm:items-center sm:justify-between"
                key={result.id}
              >
                <div>
                  <p className="text-sm font-semibold text-slate-950">
                    Attempt {result.attempt_number} · {result.score}%
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Completed {formatDateTime(result.completed_at)}
                    {result.expires_at ? ` · expires ${formatDateTime(result.expires_at)}` : ""}
                  </p>
                </div>
                <StatusBadge tone={statusTone(result.outcome)}>
                  {enumLabel(result.outcome)}
                </StatusBadge>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function ComplianceApprovalPanel({
  person,
  visit
}: {
  person: Person;
  visit: Visit;
}) {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("Compliance evaluation requested.");
  const [approval, setApproval] = useState<Approval | null>(null);
  const canRead = hasPermission("compliance:read");
  const canWrite = hasPermission("approvals:write");
  const complianceQuery = useQuery({
    queryKey: ["batch3", "compliance", visit.id],
    queryFn: () =>
      apiRequest<ComplianceEvaluation>(`/api/visits/${visit.id}/compliance`),
    enabled: canRead,
    retry: false
  });
  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<Approval>(`/api/visits/${visit.id}/approvals`, {
        method: "POST",
        body: { reason }
      }),
    onSuccess: async (createdApproval) => {
      setApproval(createdApproval);
      await invalidateBatch3Queries(queryClient, person.id, visit.id);
    }
  });
  const decisionMutation = useMutation({
    mutationFn: (decision: "approved" | "rejected" | "correction_requested") => {
      if (!approval) {
        throw new Error("Create a current approval evaluation before recording a decision.");
      }
      return apiRequest<Approval>(`/api/approvals/${approval.id}/decision`, {
        method: "POST",
        body: { decision, reason }
      });
    },
    onSuccess: async (updatedApproval) => {
      setApproval(updatedApproval);
      await invalidateBatch3Queries(queryClient, person.id, visit.id);
    }
  });

  if (!canRead) {
    return (
      <section className="surface p-5">
        <PermissionState
          className="border-0 py-6 shadow-none"
          description="This role cannot inspect the current compliance evaluation."
          title="Compliance is restricted"
        />
      </section>
    );
  }
  if (complianceQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (complianceQuery.isError) {
    return (
      <ErrorState
        description={errorMessage(complianceQuery.error) ?? undefined}
        onRetry={() => void complianceQuery.refetch()}
      />
    );
  }

  const evaluation = complianceQuery.data;
  return (
    <section className="surface p-5" aria-labelledby="compliance-workspace">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700">
            <ShieldCheck aria-hidden="true" className="h-5 w-5" />
          </span>
          <div>
            <h2 className="font-semibold text-slate-950" id="compliance-workspace">
              Compliance & approval
            </h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Review the current evidence, training, identity document, and blacklist checks below.
              Each status and eligibility decision comes from the API.
            </p>
          </div>
        </div>
        <StatusBadge tone={evaluation?.eligible ? "success" : "danger"}>
          {evaluation?.eligible ? "Eligible" : "Not eligible"}
        </StatusBadge>
      </div>

      {evaluation ? (
        <div className="mt-5 space-y-3 border-t pt-5">
          <p className="text-xs text-muted-foreground">
            {["renewi_driver", "temporary_driver", "external_driver"].includes(person.population)
              ? "Drivers must have a verified, current driving licence; an ID card is not required."
              : "Non-drivers must have a verified, current ID card; a driving licence is not required."}
            {" "}Only checks applicable to this visit are shown.
          </p>
          {evaluation.checks.map((check) => (
            <ComplianceCheckCard check={check} key={`${check.kind}-${check.code}`} />
          ))}
          <div className="text-xs leading-5 text-muted-foreground">
            <p>Compliance evaluated at effective demo time: {formatDateTime(evaluation.evaluated_at)}</p>
            <p>Current local time: {formatDateTime(new Date().toISOString())}</p>
            <p>
              The saved demo clock controls eligibility and may differ from today.
              Changing it requires a separate review of access and expiry effects.
            </p>
          </div>
        </div>
      ) : null}

      <div className="mt-5 border-t pt-5">
        <label className={labelClass}>
          Reviewer reason
          <textarea
            className={`${fieldClass} min-h-20`}
            minLength={3}
            onChange={(event) => setReason(event.target.value)}
            value={reason}
          />
        </label>
        {canWrite ? (
          <div className="mt-3 space-y-3">
            {!approval ? (
              <button
                className={primaryButton}
                disabled={createMutation.isPending || reason.trim().length < 3}
                onClick={() => createMutation.mutate()}
                type="button"
              >
                {createMutation.isPending ? "Creating evaluation…" : "Create approval evaluation"}
              </button>
            ) : (
              <div className="rounded-xl border bg-slate-50/60 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">
                      Approval snapshot created
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {formatDateTime(approval.created_at)} · {approval.compliance_snapshot.length} checks retained
                    </p>
                    {approval.decided_at ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Decision recorded {formatDateTime(approval.decided_at)}
                      </p>
                    ) : null}
                  </div>
                  <StatusBadge tone={statusTone(approval.decision)}>
                    {enumLabel(approval.decision)}
                  </StatusBadge>
                </div>
                {approval.decision === "pending" ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      className={primaryButton}
                      disabled={decisionMutation.isPending || reason.trim().length < 3}
                      onClick={() => decisionMutation.mutate("approved")}
                      type="button"
                    >
                      Approve eligible snapshot
                    </button>
                    <button
                      className={dangerButton}
                      disabled={decisionMutation.isPending || reason.trim().length < 3}
                      onClick={() => decisionMutation.mutate("rejected")}
                      type="button"
                    >
                      Reject
                    </button>
                    <button
                      className={secondaryButton}
                      disabled={decisionMutation.isPending || reason.trim().length < 3}
                      onClick={() => decisionMutation.mutate("correction_requested")}
                      type="button"
                    >
                      Request correction
                    </button>
                  </div>
                ) : null}
              </div>
            )}
            <FormError error={createMutation.error ?? decisionMutation.error} />
          </div>
        ) : (
          <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            This role can inspect checks but cannot create or decide an approval.
          </p>
        )}
      </div>
    </section>
  );
}

function ComplianceCheckCard({ check }: { check: ComplianceCheck }) {
  const Icon =
    check.status === "passed"
      ? CheckCircle2
      : check.status === "blocked" || check.status === "failed"
        ? XCircle
        : AlertTriangle;

  return (
    <article className="rounded-xl border bg-slate-50/60 p-4">
      <div className="flex items-start gap-3">
        <Icon
          aria-hidden="true"
          className={`mt-0.5 h-5 w-5 ${
            check.status === "passed"
              ? "text-emerald-700"
              : check.status === "blocked" || check.status === "failed"
                ? "text-red-700"
                : "text-amber-700"
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-950">{check.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">{check.detail}</p>
            </div>
            <StatusBadge tone={complianceTone(check.status)}>
              {enumLabel(check.status)}
            </StatusBadge>
          </div>
          <p className="mt-2 font-mono text-[0.6875rem] text-slate-500">
            {check.code} · {enumLabel(check.kind)}
            {check.blocking ? " · blocking" : " · advisory"}
          </p>
        </div>
      </div>
    </article>
  );
}

function BlacklistPanel({
  person,
  company
}: {
  person: Person;
  company: Company | undefined;
}) {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [subjectType, setSubjectType] = useState<BlacklistSubjectType>("person");
  const [reason, setReason] = useState("");
  const canRead = hasPermission("blacklist:read");
  const canWrite = hasPermission("blacklist:write");
  const blacklistQuery = useQuery({
    queryKey: ["batch3", "blacklist"],
    queryFn: () => apiRequest<BlacklistEntry[]>("/api/blacklist"),
    enabled: canRead,
    retry: false
  });
  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<BlacklistEntry>("/api/blacklist", {
        method: "POST",
        body: {
          subject_type: subjectType,
          person_id: subjectType === "person" ? person.id : null,
          company_id: subjectType === "company" ? person.company_id : null,
          reason
        }
      }),
    onSuccess: async () => {
      setReason("");
      await invalidateBatch3Queries(queryClient, person.id);
    }
  });
  const revokeMutation = useMutation({
    mutationFn: (entryId: string) =>
      apiRequest<BlacklistEntry>(`/api/blacklist/${entryId}/revoke`, {
        method: "POST",
        body: { reason: "Blacklist entry revoked following review." }
      }),
    onSuccess: async () => {
      await invalidateBatch3Queries(queryClient, person.id);
    }
  });

  if (!canRead) {
    return null;
  }
  if (blacklistQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (blacklistQuery.isError) {
    return (
      <ErrorState
        description={errorMessage(blacklistQuery.error) ?? undefined}
        onRetry={() => void blacklistQuery.refetch()}
      />
    );
  }

  const relatedEntries = (blacklistQuery.data ?? []).filter(
    (entry) => entry.person_id === person.id || entry.company_id === person.company_id
  );
  return (
    <section className="surface p-5" aria-labelledby="blacklist-management">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-red-50 text-red-700">
          <Ban aria-hidden="true" className="h-5 w-5" />
        </span>
        <div>
          <h2 className="font-semibold text-slate-950" id="blacklist-management">
            Blacklist management
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Authoritative blacklist records block approval and token issue. Revocation retains historical evidence.
          </p>
        </div>
      </div>

      {canWrite ? (
        <div className="mt-5 space-y-3 border-t pt-5">
          <label className={labelClass}>
            Target
            <select
              className={fieldClass}
              onChange={(event) => setSubjectType(event.target.value as BlacklistSubjectType)}
              value={subjectType}
            >
              <option value="person">
                Person · {person.first_name} {person.last_name}
              </option>
              <option disabled={!company} value="company">
                Company · {company?.name ?? "Company information restricted"}
              </option>
            </select>
          </label>
          <label className={labelClass}>
            Reason
            <textarea
              className={`${fieldClass} min-h-20`}
              minLength={3}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Document the synthetic demo reason."
              value={reason}
            />
          </label>
          <button
            className={dangerButton}
            disabled={createMutation.isPending || reason.trim().length < 3}
            onClick={() => createMutation.mutate()}
            type="button"
          >
            <ShieldAlert aria-hidden="true" className="h-4 w-4" />
            {createMutation.isPending ? "Adding blacklist entry…" : "Add blacklist entry"}
          </button>
          <FormError error={createMutation.error} />
        </div>
      ) : null}

      <div className="mt-5 border-t pt-5">
        <h3 className="text-sm font-semibold text-slate-950">Related records</h3>
        {relatedEntries.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No person or company blacklist history is visible for this visit.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {relatedEntries.map((entry) => (
              <article className="rounded-xl border bg-slate-50/60 p-3" key={entry.id}>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">
                      {enumLabel(entry.subject_type)} blacklist
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{entry.reason}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Started {formatDateTime(entry.starts_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={entry.is_active ? "danger" : "neutral"}>
                      {entry.is_active ? "Active" : "Revoked"}
                    </StatusBadge>
                    {canWrite && entry.is_active ? (
                      <button
                        className="text-xs font-semibold text-emerald-800 hover:text-emerald-950"
                        disabled={revokeMutation.isPending}
                        onClick={() => revokeMutation.mutate(entry.id)}
                        type="button"
                      >
                        Revoke
                      </button>
                    ) : null}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        <FormError error={revokeMutation.error} />
      </div>
    </section>
  );
}

// A datetime-local input wants "YYYY-MM-DDTHH:mm". It is read on the site's clock (Amsterdam time).
const toLocalInput = isoToSiteInput;

function AccessTokenPanel({ visit }: { visit: Visit }) {
  const { hasPermission } = useAuth();
  // The site's longest-QR rule (hours), set by an administrator on the Settings page.
  const siteSettingsQuery = useQuery({
    queryKey: ["site-settings"],
    queryFn: () =>
      apiRequest<{ site_id: string; access_qr_max_hours: number }[]>("/api/site-settings")
  });
  const maxQrHours =
    siteSettingsQuery.data?.find((row) => row.site_id === visit.site_id)?.access_qr_max_hours ?? 24;
  // Entry and exit time of the QR. They start as the visit window, limited to the longest allowed.
  const [entryFrom, setEntryFrom] = useState(() => toLocalInput(visit.starts_at));
  const [exitByChoice, setExitByChoice] = useState<string | null>(null);
  const defaultExit = (() => {
    const start = entryFrom
      ? new Date(siteInputToIso(entryFrom)).getTime()
      : new Date(visit.starts_at).getTime();
    const latest = Math.min(new Date(visit.ends_at).getTime(), start + maxQrHours * 3600000);
    return toLocalInput(new Date(latest).toISOString());
  })();
  const exitBy = exitByChoice ?? defaultExit;
  const setExitBy = (value: string) => setExitByChoice(value);
  const entryMs = entryFrom ? new Date(siteInputToIso(entryFrom)).getTime() : NaN;
  const exitMs = exitBy ? new Date(siteInputToIso(exitBy)).getTime() : NaN;
  const windowError =
    !entryFrom || !exitBy
      ? "Choose both an entry time and an exit time."
      : entryMs < new Date(visit.starts_at).getTime()
        ? "The entry time cannot be before the visit starts."
        : exitMs > new Date(visit.ends_at).getTime()
          ? "The exit time cannot be after the visit ends."
          : entryMs >= exitMs
            ? "The entry time must be before the exit time."
            : exitMs - entryMs > maxQrHours * 3600000
              ? `This site allows an access QR to last at most ${maxQrHours} hours. Choose an earlier exit time.`
              : null;
  const queryClient = useQueryClient();
  const [issuedToken, setIssuedToken] = useState<TokenIssueResponse | null>(null);
  const tokenIssuanceInFlight = useRef(false);
  const [revokeReason, setRevokeReason] = useState(
    "Access token revoked during synthetic demo review."
  );
  const canRead = hasPermission("tokens:read");
  const canWrite = hasPermission("tokens:write");
  const canReadClock = hasPermission("expiry:read");
  const tokensQuery = useQuery({
    queryKey: ["batch3", "tokens", visit.id],
    queryFn: () => apiRequest<AccessToken[]>(`/api/visits/${visit.id}/tokens`),
    enabled: canRead,
    retry: false
  });
  const clockQuery = useQuery({
    queryKey: ["batch6", "demo-clock"],
    queryFn: () => apiRequest<DemoClock>("/api/demo-clock"),
    // Clock visibility is separate from token issuance permission.
    enabled: canWrite && canReadClock,
    retry: false,
    // An uninitialized demo clock follows host time, so refresh before offering issuance.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true
  });
  const visitHasEnded = clockQuery.data
    ? new Date(visit.ends_at).getTime() <= new Date(clockQuery.data.effective_at).getTime()
    : false;
  const issueMutation = useMutation({
    mutationFn: () =>
      apiRequest<TokenIssueResponse>(`/api/visits/${visit.id}/tokens`, {
        method: "POST",
        body: {
          valid_from: siteInputToIso(entryFrom),
          expires_at: siteInputToIso(exitBy)
        }
      }),
    onSuccess: async (response) => {
      setIssuedToken(response);
      await invalidateBatch3Queries(queryClient, undefined, visit.id);
    }
  });
  const issueToken = () => {
    // React Query updates isPending on the next render. This ref closes the
    // short interval in which a repeated click could otherwise create a
    // second request before the button becomes disabled.
    // Only roles allowed to read the clock use it as a client-side guard;
    // the token API enforces visit expiry for every role.
    if (windowError || tokenIssuanceInFlight.current || (canReadClock && (clockQuery.isPending || clockQuery.isError || visitHasEnded))) {
      return;
    }

    tokenIssuanceInFlight.current = true;
    issueMutation.mutate(undefined, {
      onSettled: () => {
        tokenIssuanceInFlight.current = false;
      }
    });
  };
  const revokeMutation = useMutation({
    mutationFn: (tokenId: string) =>
      apiRequest<AccessToken>(`/api/tokens/${tokenId}/revoke`, {
        method: "POST",
        body: { reason: revokeReason }
      }),
    onSuccess: async () => {
      await invalidateBatch3Queries(queryClient, undefined, visit.id);
    }
  });

  if (!canRead) {
    return (
      <section className="surface p-5">
        <PermissionState
          className="border-0 py-6 shadow-none"
          description="Access-token metadata is unavailable to this role."
          title="Token management is restricted"
        />
      </section>
    );
  }
  if (tokensQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (tokensQuery.isError) {
    return (
      <ErrorState
        description={errorMessage(tokensQuery.error) ?? undefined}
        onRetry={() => void tokensQuery.refetch()}
      />
    );
  }

  const tokens = tokensQuery.data ?? [];
  return (
    <section className="surface p-5" aria-labelledby="access-token-management">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
          <KeyRound aria-hidden="true" className="h-5 w-5" />
        </span>
        <div>
          <h2 className="font-semibold text-slate-950" id="access-token-management">
            QR access token
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Token metadata is retained for audit. The opaque QR payload is revealed only once after issue and is rendered locally.
          </p>
        </div>
      </div>

      {canWrite ? (
        <div className="mt-5 border-t pt-5">
          {clockQuery.data ? (
            <p className="mb-3 text-sm text-muted-foreground">
              Effective demo time: {formatDateTime(clockQuery.data.effective_at)}.
              Visit ends: {formatDateTime(visit.ends_at)}.
              This is the API&apos;s simulated time for access and expiry checks,
              not necessarily the current wall-clock time.
            </p>
          ) : null}
          {visitHasEnded ? (
            <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
              This visit ended before the effective demo time. A token cannot be issued
              after its visit ends. Select a visit with a valid future end time, or
              arrange an authorized update to the visit schedule if the dates are wrong.
            </p>
          ) : null}
          {canReadClock && clockQuery.isError ? (
            <p className="mb-3 text-sm text-red-700" role="alert">
              Effective demo time is unavailable. Reload this page before issuing a token.
            </p>
          ) : null}
          {!canReadClock ? (
            <p className="mb-3 text-sm text-muted-foreground">
              Visit ends: {formatDateTime(visit.ends_at)}. The API will check
              the effective demo time and reject an ended visit.
            </p>
          ) : null}
          <fieldset className="mb-4 rounded-xl border border-slate-200 p-4">
            <legend className="px-1 text-sm font-semibold text-slate-950">
              When the QR works
            </legend>
            <div className="flex flex-wrap gap-4">
              <label className="text-sm text-slate-700">
                Entry from
                <input
                  className="mt-1 block rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                  min={toLocalInput(visit.starts_at)}
                  max={toLocalInput(visit.ends_at)}
                  onChange={(event) => setEntryFrom(event.target.value)}
                  type="datetime-local"
                  value={entryFrom}
                />
              </label>
              <label className="text-sm text-slate-700">
                Exit by
                <input
                  className="mt-1 block rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                  min={toLocalInput(visit.starts_at)}
                  max={toLocalInput(visit.ends_at)}
                  onChange={(event) => setExitBy(event.target.value)}
                  type="datetime-local"
                  value={exitBy}
                />
              </label>
            </div>
            <p className="mt-2 text-xs text-slate-700">
              Enter these on the Amsterdam clock.
              {entryFrom && exitBy && !windowError && yourClockHint(siteInputToIso(entryFrom))
                ? ` On your clock that is ${yourClockHint(siteInputToIso(entryFrom))} to ${yourClockHint(siteInputToIso(exitBy))}.`
                : ""}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Starts as the visit window ({formatDateTime(visit.starts_at)} to{" "}
              {formatDateTime(visit.ends_at)}) and can be narrowed, not widened. An administrator limits an access QR to {maxQrHours} hours at this site. The gate refuses
              the QR before the entry time and after the exit time.
            </p>
            {windowError ? <p className="mt-2 text-sm text-red-700">{windowError}</p> : null}
          </fieldset>
          <button
            className={primaryButton}
            disabled={Boolean(windowError) || issueMutation.isPending || (canReadClock && (clockQuery.isPending || clockQuery.isError || visitHasEnded))}
            onClick={issueToken}
            type="button"
          >
            <KeyRound aria-hidden="true" className="h-4 w-4" />
            {issueMutation.isPending ? "Issuing token…" : "Issue eligible visit token"}
          </button>
          <FormError error={issueMutation.error} />
        </div>
      ) : null}

      {issuedToken ? (
        <>
          <p className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800" role="status">
            {issuedToken.delivery_status === "smtp_sent"
              ? "The gate-readable QR image was handed to the invitation recipient's email server. The invitee can download the PNG attachment and bring it to the gate."
              : issuedToken.delivery_status === "smtp_failed"
                ? "The token was issued, but email delivery failed. Download the one-time QR now and arrange secure delivery to the invitee; issuing again will not recover this payload."
                : issuedToken.delivery_status === "local_only"
                  ? "The token was issued, but email is not configured. Download the one-time QR now and arrange secure delivery to the invitee."
                  : "The token was issued, but no matching accepted invitation recipient was found. Download the one-time QR now; do not send it to an unverified address."}
          </p>
          <QrCard response={issuedToken} />
        </>
      ) : (
        <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-muted-foreground">
          Issue succeeds only when the API finds a current approved, eligible visit. A QR card appears here once and is not recoverable from token history.
        </p>
      )}

      <div className="mt-5 border-t pt-5">
        <h3 className="text-sm font-semibold text-slate-950">Issued token history</h3>
        {tokens.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No access tokens have been issued for this visit.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {tokens.map((token) => (
              <article
                className="flex flex-col gap-3 rounded-xl border bg-slate-50/60 p-3 sm:flex-row sm:items-center sm:justify-between"
                key={token.id}
              >
                <div>
                  <p className="text-sm font-semibold text-slate-950">
                    Issued {formatDateTime(token.issued_at)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {token.valid_from ? `Entry ${formatDateTime(token.valid_from)} · ` : ""}Exit {formatDateTime(token.expires_at)}
                    {token.revoke_reason ? ` · ${token.revoke_reason}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone={statusTone(token.status)}>
                    {enumLabel(token.status)}
                  </StatusBadge>
                  {canWrite && token.status === "active" ? (
                    <button
                      className="text-xs font-semibold text-red-700 hover:text-red-900"
                      disabled={revokeMutation.isPending}
                      onClick={() => revokeMutation.mutate(token.id)}
                      type="button"
                    >
                      Revoke
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
        {canWrite ? (
          <label className={`${labelClass} mt-4 block`}>
            Revocation reason
            <input
              className={fieldClass}
              minLength={3}
              onChange={(event) => setRevokeReason(event.target.value)}
              value={revokeReason}
            />
          </label>
        ) : null}
        <FormError error={revokeMutation.error} />
      </div>
    </section>
  );
}

function QrCard({
  response
}: {
  response: TokenIssueResponse;
}) {
  const printableId = `qr-token-${response.token.id}`;

  function downloadQr() {
    const svg = document.querySelector(`#${printableId} svg`);
    if (!svg) {
      return;
    }

    // Export the displayed QR, not token metadata: the one-time payload is
    // never available from token history after this card is dismissed.
    const serialized = new XMLSerializer().serializeToString(svg);
    const url = URL.createObjectURL(
      new Blob([serialized], { type: "image/svg+xml;charset=utf-8" })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `renewi-access-qr-${response.token.id}.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function printQrCard() {
    const printable = document.getElementById(printableId);
    if (!printable) {
      return;
    }
    // A noopener popup may return null, leaving no window to print.
    const popup = window.open("", "_blank");
    if (!popup) {
      return;
    }
    popup.opener = null;
    popup.document.write(`
      <!doctype html>
      <html lang="en">
        <head>
          <title>Renewi Access QR card</title>
          <style>
            body { font-family: Arial, sans-serif; margin: 28px; color: #0f172a; }
            .card { border: 2px solid #047857; border-radius: 18px; max-width: 480px; padding: 28px; }
            h1 { font-size: 22px; margin: 0; } p { line-height: 1.45; }
            svg { display: block; margin: 24px auto; }
          </style>
        </head>
        <body>${printable.outerHTML}</body>
      </html>
    `);
    popup.document.close();
    popup.focus();
    popup.print();
  }

  return (
    <div className="mt-5 rounded-xl border-2 border-emerald-200 bg-emerald-50/50 p-5">
      <div id={printableId}>
        <p className="eyebrow text-emerald-800">One-time QR payload</p>
        <h3 className="mt-2 text-lg font-semibold text-slate-950">Renewi Access</h3>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-slate-700">
          {response.valid_from ? (
            <>
              <dt className="font-semibold">Entry from</dt>
              <dd>{formatInSiteZone(response.valid_from, response.site_timezone)}</dd>
            </>
          ) : null}
          <dt className="font-semibold">Exit by</dt>
          <dd>{formatInSiteZone(response.token.expires_at, response.site_timezone)}</dd>
        </dl>
        <div className="mt-5 flex justify-center rounded-xl bg-white p-5">
          <QRCodeSVG
            bgColor="#ffffff"
            fgColor="#052e16"
            includeMargin
            level="M"
            size={208}
            value={response.qr_payload}
          />
        </div>
        <p className="mt-4 text-center text-xs text-slate-600">
          Opaque visit-bound reference · synthetic demo only
        </p>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <button className={secondaryButton} onClick={downloadQr} type="button">
          Download QR
        </button>
        <button className={secondaryButton} onClick={printQrCard} type="button">
          <Printer aria-hidden="true" className="h-4 w-4" />
          Print QR card
        </button>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-600">
        Keep this card available only for the intended visitor. The API stores only a hash and token history never reveals this payload again.
      </p>
    </div>
  );
}
