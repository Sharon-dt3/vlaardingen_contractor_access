"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { ErrorState, PermissionState } from "@/components/states/content-state";
import { PageSkeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import type {
  CurrentPresence,
  DemoClock,
  Evidence,
  OnSiteIdRenewalResponse
} from "@/lib/domain";

const fieldClass =
  "mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-emerald-600";
const primaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50";

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The on-site ID renewal workspace could not be loaded.";
}

function nextDate(date: string): string {
  const next = new Date(`${date}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString().slice(0, 10);
}

// PUBLIC_INTERFACE
/**
 * Lets authorized operators propose a later non-driver ID expiry for an
 * on-site person. The verified roster expiry changes only after evidence review.
 */
export function ExpiryRevalidationWorkspace() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [submission, setSubmission] = useState<OnSiteIdRenewalResponse | null>(null);

  const canRead = hasPermission("expiry:read");
  const canWrite = hasPermission("expiry:write");
  const canReadPresence = hasPermission("presence:read");
  const canReadEvidence = hasPermission("evidence:read");

  const presenceQuery = useQuery({
    queryKey: ["presence", "all"],
    queryFn: () => apiRequest<CurrentPresence[]>("/api/presence"),
    enabled: canRead && canReadPresence,
    retry: false
  });
  const clockQuery = useQuery({
    queryKey: ["batch6", "demo-clock"],
    queryFn: () => apiRequest<DemoClock>("/api/demo-clock"),
    enabled: canRead && canWrite && canReadPresence && canReadEvidence,
    retry: false
  });

  const people = Array.from(
    new Map(
      (presenceQuery.data ?? [])
        .filter((person) => ![
          "renewi_driver",
          "temporary_driver",
          "external_driver"
        ].includes(person.population))
        .map((person) => [person.person_id, person] as const)
    ).values()
  ).sort((a, b) => a.person_name.localeCompare(b.person_name));
  const selectedPerson = people.find((person) => person.person_id === selectedPersonId);

  const evidenceQuery = useQuery({
    queryKey: ["records", "person-evidence", selectedPerson?.person_id],
    queryFn: () =>
      apiRequest<Evidence[]>(`/api/people/${encodeURIComponent(selectedPerson!.person_id)}/evidence`),
    enabled: canRead && canWrite && canReadEvidence && !!selectedPerson,
    retry: false
  });

  // Match the backend's latest-verified ordering; an uploaded proposal is not
  // a verified source and must never replace the currently displayed ID date.
  const verifiedId = [...(evidenceQuery.data ?? [])]
    .filter((item) => item.evidence_type === "id_card" && item.status === "verified")
    .sort((a, b) =>
      b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id)
    )[0];
  const pendingRenewal = !!verifiedId && (evidenceQuery.data ?? []).some(
    (item) =>
      item.supersedes_id === verifiedId.id &&
      (item.status === "uploaded" || item.status === "extracted")
  );
  const effectiveDate = clockQuery.data?.effective_at.slice(0, 10);
  const minimumDate = effectiveDate
    ? nextDate(
        selectedPerson?.id_expiry_date && selectedPerson.id_expiry_date > effectiveDate
          ? selectedPerson.id_expiry_date
          : effectiveDate
      )
    : undefined;

  const renewalMutation = useMutation({
    mutationFn: (request: { person_id: string; source_id: string; expiry_date: string }) =>
      apiRequest<OnSiteIdRenewalResponse>("/api/expiry/on-site-id-renewals", {
        method: "POST",
        body: request
      }),
    onMutate: () => setSubmission(null),
    onSuccess: async (result) => {
      setSubmission(result);
      setExpiryDate("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", "person-evidence", result.person_id] }),
        queryClient.invalidateQueries({ queryKey: ["presence"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      ]);
    }
  });

  function submitRenewal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !canWrite ||
      !canReadPresence ||
      !canReadEvidence ||
      !selectedPerson ||
      !verifiedId ||
      pendingRenewal ||
      !minimumDate ||
      !expiryDate ||
      expiryDate < minimumDate ||
      renewalMutation.isPending
    ) {
      return;
    }
    renewalMutation.mutate({
      person_id: selectedPerson.person_id,
      source_id: verifiedId.id,
      expiry_date: expiryDate
    });
  }

  if (!canRead) {
    return (
      <PermissionState
        description="Your current role cannot access expiry controls."
        title="Expiry management is restricted"
      />
    );
  }

  return (
    <section aria-labelledby="expiry-revalidation-workspace" className="surface p-5">
      <div className="flex items-center gap-2">
        <CalendarClock aria-hidden="true" className="h-5 w-5 text-emerald-700" />
        <h2 className="text-base font-semibold text-slate-950" id="expiry-revalidation-workspace">
          Expiry control workspace
        </h2>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        Select a person currently on site to view their verified ID expiry and propose
        a later date. Driver IDs cannot be renewed here. A proposal remains pending
        review; the on-site roster changes only after authorized verification.
      </p>

      {!canWrite || !canReadPresence || !canReadEvidence ? (
        <p className="mt-4 text-sm text-amber-800">
          Expiry-write, presence-read, and evidence-read permissions are required to
          propose an on-site ID renewal.
        </p>
      ) : presenceQuery.error || clockQuery.error ? (
        <ErrorState
          className="mt-4"
          description={errorMessage(presenceQuery.error ?? clockQuery.error)}
          onRetry={() => {
            void presenceQuery.refetch();
            void clockQuery.refetch();
          }}
          title="On-site ID controls could not be loaded"
        />
      ) : presenceQuery.isLoading || clockQuery.isLoading ? (
        <div className="mt-4"><PageSkeleton /></div>
      ) : (
        <>
          {people.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">
              No non-driver is currently on site.
            </p>
          ) : null}
          <form className="mt-4 grid gap-4 md:grid-cols-2" onSubmit={submitRenewal}>
            <div>
              <label className="text-sm font-semibold text-slate-800" htmlFor="renewal-person">
                On-site person
              </label>
              <select
                className={fieldClass}
                disabled={people.length === 0 || renewalMutation.isPending}
                id="renewal-person"
                onChange={(event) => {
                  setSelectedPersonId(event.target.value);
                  setExpiryDate("");
                  setSubmission(null);
                  renewalMutation.reset();
                }}
                required
                value={selectedPerson?.person_id ?? ""}
              >
                <option value="">Select a person</option>
                {people.map((person) => (
                  <option key={person.person_id} value={person.person_id}>
                    {person.person_name} · {person.site_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800">Current verified ID expiry</p>
              <p className="mt-1.5 rounded-lg border bg-slate-50 px-3 py-2.5 text-sm text-slate-800">
                {selectedPerson
                  ? selectedPerson.id_expiry_date ?? "No verified ID expiry available"
                  : "Select a person to view their ID expiry"}
              </p>
            </div>
            {selectedPerson ? (
              <div className="md:col-span-2">
                {evidenceQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading verified ID evidence…</p>
                ) : evidenceQuery.error ? (
                  <ErrorState
                    description={errorMessage(evidenceQuery.error)}
                    onRetry={() => void evidenceQuery.refetch()}
                    title="Verified ID evidence could not be loaded"
                  />
                ) : !verifiedId || !selectedPerson.id_expiry_date ? (
                  <p className="text-sm text-amber-800">
                    This person has no renewable verified ID with an expiry date.
                  </p>
                ) : pendingRenewal ? (
                  <p className="text-sm text-amber-800" role="status">
                    An ID expiry proposal is pending review. The roster still shows the verified date.
                  </p>
                ) : null}
              </div>
            ) : null}
            <div>
              <label className="text-sm font-semibold text-slate-800" htmlFor="renewal-expiry">
                Proposed new ID expiry date
              </label>
              <input
                className={fieldClass}
                disabled={
                  !selectedPerson?.id_expiry_date ||
                  !verifiedId ||
                  pendingRenewal ||
                  !minimumDate ||
                  renewalMutation.isPending
                }
                id="renewal-expiry"
                min={minimumDate}
                onChange={(event) => setExpiryDate(event.target.value)}
                required
                type="date"
                value={expiryDate}
              />
            </div>
            <div className="flex items-end">
              <button
                className={primaryButton}
                disabled={
                  !selectedPerson?.id_expiry_date ||
                  !verifiedId ||
                  pendingRenewal ||
                  !minimumDate ||
                  !expiryDate ||
                  expiryDate < minimumDate ||
                  renewalMutation.isPending
                }
                type="submit"
              >
                {renewalMutation.isPending ? "Submitting…" : "Propose ID renewal for review"}
              </button>
            </div>
          </form>
          {renewalMutation.error ? (
            <p aria-live="assertive" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {errorMessage(renewalMutation.error)}
            </p>
          ) : null}
          {submission ? (
            <p
              aria-live="polite"
              className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              role="status"
            >
              Proposed ID expiry {submission.expiry_date} submitted as pending review.
              The on-site roster will continue to show the verified expiry until
              authorized review verifies the evidence.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
