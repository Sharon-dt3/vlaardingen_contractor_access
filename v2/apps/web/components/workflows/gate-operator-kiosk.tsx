"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  XCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { ErrorState } from "@/components/states/content-state";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { apiPrivateBlobPost, apiRequest } from "@/lib/api-client";
import type {
  Company,
  GateCheck,
  GateDecisionResponse,
  GateEvaluationRequest,
  GatePresentation,
  Invitation,
  Person,
  Site,
  Visit
} from "@/lib/domain";
import { enumLabel, formatDateTime, formatInSiteZone } from "@/lib/domain";
import { GateQrScanner } from "./gate-qr-scanner";

type KioskStage = "scan" | "verify" | "decision";

const fieldClass =
  "mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-emerald-600";
const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-600";
const primaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : "The gate request could not be completed.";
}

function decisionTone(decision: GateDecisionResponse["decision"]): StatusTone {
  return decision === "GRANT" ? "success" : "danger";
}

function checkTone(check: GateCheck): StatusTone {
  if (check.status === "passed") {
    return "success";
  }
  return check.blocking ? "danger" : "warning";
}

function StageIndicator({
  activeStage,
  stage,
  title
}: {
  activeStage: KioskStage;
  stage: KioskStage;
  title: string;
}) {
  const stages: KioskStage[] = ["scan", "verify", "decision"];
  const activeIndex = stages.indexOf(activeStage);
  const index = stages.indexOf(stage);
  const isCurrent = activeStage === stage;
  const isComplete = activeIndex > index;

  return (
    <li className="flex min-w-[7rem] items-center gap-2">
      <span
        aria-hidden="true"
        className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${
          isCurrent
            ? "bg-emerald-700 text-white"
            : isComplete
              ? "bg-emerald-100 text-emerald-800"
              : "bg-slate-100 text-slate-500"
        }`}
      >
        {isComplete ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
      </span>
      <span className={`text-sm font-semibold ${isCurrent ? "text-slate-950" : "text-slate-500"}`}>
        {title}
      </span>
    </li>
  );
}

// PUBLIC_INTERFACE
/**
 * Presents live registered visits and an uploaded-QR Gate workflow. Names
 * provide operator context only: the API resolves identity from the scanned
 * QR token, validates uploads, and makes every final access decision.
 */
export function GateOperatorKiosk() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<KioskStage>("scan");
  const [selectedVisitId, setSelectedVisitId] = useState("");
  const [tokenReference, setTokenReference] = useState("");
  const [siteId, setSiteId] = useState("");
  const [scanError, setScanError] = useState<string | null>(null);
  const [comparisonConfirmed, setComparisonConfirmed] = useState(false);
  const [preview, setPreview] = useState<{
    key: string;
    kind: "image" | "pdf" | "text";
    url?: string;
    text?: string;
  } | null>(null);

  useEffect(() => {
    return () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  const sitesQuery = useQuery({
    queryKey: ["records", "sites"],
    queryFn: () => apiRequest<Site[]>("/api/sites"),
    enabled: hasPermission("sites:read"),
    retry: false
  });
  const peopleQuery = useQuery({
    queryKey: ["records", "people"],
    queryFn: () => apiRequest<Person[]>("/api/people"),
    enabled: hasPermission("people:read"),
    retry: false
  });
  const companiesQuery = useQuery({
    queryKey: ["records", "companies"],
    queryFn: () => apiRequest<Company[]>("/api/companies"),
    enabled: hasPermission("companies:read"),
    retry: false
  });
  const visitsQuery = useQuery({
    queryKey: ["records", "visits"],
    queryFn: () => apiRequest<Visit[]>("/api/visits"),
    enabled: hasPermission("visits:read"),
    retry: false
  });
  const invitationsQuery = useQuery({
    queryKey: ["workflows", "invitations"],
    queryFn: () => apiRequest<Invitation[]>("/api/invitations"),
    enabled: hasPermission("invitations:read"),
    retry: false
  });

  const candidates = useMemo(() => {
    const people = new Map((peopleQuery.data ?? []).map((person) => [person.id, person]));
    const invitations = new Map(
      (invitationsQuery.data ?? [])
        .filter((invitation) => invitation.visit_id && invitation.person_id)
        .map((invitation) => [invitation.visit_id as string, invitation])
    );
    return (visitsQuery.data ?? []).flatMap((visit) => {
      const person = people.get(visit.person_id);
      if (!person) {
        return [];
      }
      const invitation = invitations.get(visit.id) ?? null;
      // Where invitations are visible, list only correctly linked registered
      // visits. Gate-only accounts cannot read invitations, so they see visits
      // as context but still need the physical QR for any API action.
      if (hasPermission("invitations:read") && (
        !invitation || invitation.person_id !== person.id || invitation.site_id !== visit.site_id
      )) {
        return [];
      }
      return [{ visit, person, invitation }];
    });
  }, [
    hasPermission,
    invitationsQuery.data,
    peopleQuery.data,
    visitsQuery.data
  ]);
  const selectedCandidate = candidates.find((item) => item.visit.id === selectedVisitId);
  const presentationQuery = useQuery({
    queryKey: ["gate", "presentation", tokenReference, siteId],
    queryFn: () => apiRequest<GatePresentation>("/api/gate/presentation", {
      method: "POST",
      body: { token_reference: tokenReference, site_id: siteId }
    }),
    enabled: stage === "verify" && !!tokenReference && !!siteId,
    retry: false,
    staleTime: 0
  });
  const presentation = presentationQuery.data;

  const previewMutation = useMutation({
    mutationFn: async (upload: GatePresentation["uploads"][number]) => {
      if (!presentation || !tokenReference || !siteId) {
        throw new Error("Scan a current issued QR before viewing private uploads.");
      }
      const key = `${upload.kind}:${upload.id ?? "invitation"}`;
      const type = upload.media_type.toLowerCase();
      const kind = type === "application/pdf" ? "pdf"
        : ["image/png", "image/jpeg"].includes(type) ? "image"
        : ["text/plain", "application/json"].includes(type) ? "text" : null;
      if (!kind) throw new Error("This file format cannot be safely previewed in the browser.");
      const path = `/api/gate/presentation/uploads/${upload.kind}/content${upload.id ? `?evidence_id=${encodeURIComponent(upload.id)}` : ""}`;
      const blob = await apiPrivateBlobPost(path, { token_reference: tokenReference, site_id: siteId });
      if (kind === "text") return { key, kind, text: await blob.text() } as const;
      return { key, kind, url: URL.createObjectURL(new Blob([blob], { type })) } as const;
    },
    onSuccess: (result) => {
      setPreview(result);
    }
  });

  useEffect(() => {
    if (!selectedVisitId && candidates.length > 0) {
      setSelectedVisitId(candidates[0].visit.id);
    }
  }, [candidates, selectedVisitId]);

  useEffect(() => {
    const defaultSite = sitesQuery.data?.find((site) => site.is_active);
    if (!siteId && defaultSite) {
      setSiteId(defaultSite.id);
    }
  }, [siteId, sitesQuery.data]);

  const evaluationMutation = useMutation({
    mutationFn: (payload: GateEvaluationRequest) =>
      apiRequest<GateDecisionResponse>("/api/gate/evaluations", {
        method: "POST",
        body: payload
      }),
    onSuccess: async () => {
      // The API has committed the decision and, for a grant, its entry event.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["presence"] })
      ]);
      setStage("decision");
    }
  });

  const decision = evaluationMutation.data;
  const person = peopleQuery.data?.find((candidate) => candidate.id === decision?.person_id);
  const company = companiesQuery.data?.find((candidate) => candidate.id === person?.company_id);
  const visit = visitsQuery.data?.find((candidate) => candidate.id === decision?.visit_id);
  const requestedSite = sitesQuery.data?.find(
    (candidate) => candidate.id === decision?.requested_site_id
  );

  const isLoadingRecords =
    sitesQuery.isLoading ||
    peopleQuery.isLoading ||
    companiesQuery.isLoading ||
    visitsQuery.isLoading ||
    invitationsQuery.isLoading;

  if (isLoadingRecords) {
    return <PageSkeleton />;
  }

  const recordError =
    sitesQuery.error ??
    peopleQuery.error ??
    companiesQuery.error ??
    visitsQuery.error ??
    invitationsQuery.error;
  if (recordError) {
    return (
      <ErrorState
        description={errorMessage(recordError) ?? undefined}
        onRetry={() => {
          void sitesQuery.refetch();
          void peopleQuery.refetch();
          void companiesQuery.refetch();
          void visitsQuery.refetch();
          if (hasPermission("invitations:read")) {
            void invitationsQuery.refetch();
          }
        }}
      />
    );
  }

  function clearPresentation() {
    evaluationMutation.reset();
    setTokenReference("");
    setScanError(null);
    setComparisonConfirmed(false);
    setPreview(null);
    previewMutation.reset();
    setStage("scan");
  }

  function selectCandidate(visitId: string) {
    clearPresentation();
    setSelectedVisitId(visitId);
    const candidate = candidates.find((item) => item.visit.id === visitId);
    if (candidate) {
      setSiteId(candidate.visit.site_id);
    }
  }

  function acceptScan(payload: string) {
    // The scanned QR is the only source of the opaque credential. Do not
    // reconstruct it from a selected visit or token-history metadata.
    const reference = payload.trim();
    if (reference.length < 12 || reference.length > 512) {
      setScanError("This QR is not a valid access-token reference.");
      return;
    }
    setTokenReference(reference);
    setScanError(null);
    setComparisonConfirmed(false);
    setPreview(null);
    setStage("verify");
  }

  function evaluateGate() {
    if (!siteId || !tokenReference || !presentation || !comparisonConfirmed || evaluationMutation.isPending) {
      return;
    }
    evaluationMutation.mutate({
      token_reference: tokenReference,
      site_id: siteId,
      // The server independently evaluates identity and all access checks.
      presentation_reference: "demo-presentation",
      comparison_confirmed: comparisonConfirmed
    });
  }

  return (
    <div className="space-y-7">
      <PageHeader
        badge={<StatusBadge tone="demo">Server-authoritative</StatusBadge>}
        description="Scan the issued QR, compare the invitation uploads with physical documents, then request the API's entry decision. Selecting a name never grants entry."
        eyebrow="Steps 7–8 · Gate operation"
        title="Gate operator kiosk"
      />

      <section aria-label="Gate evaluation progress" className="surface overflow-x-auto px-5 py-4">
        <ol className="flex min-w-max items-center gap-5 sm:gap-10">
          <StageIndicator activeStage={stage} stage="scan" title="Scan" />
          <ArrowRight aria-hidden="true" className="h-4 w-4 text-slate-300" />
          <StageIndicator activeStage={stage} stage="verify" title="Verify" />
          <ArrowRight aria-hidden="true" className="h-4 w-4 text-slate-300" />
          <StageIndicator activeStage={stage} stage="decision" title="Decision" />
        </ol>
      </section>

      {stage === "scan" ? (
        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(19rem,0.85fr)]">
          <div className="surface p-5 sm:p-6">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
                <ScanLine aria-hidden="true" className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Scan an access QR</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  Upload an image of the QR card issued for the visit. The
                  selected name supplies context, not a credential.
                </p>
              </div>
            </div>
            <div className="mt-6 grid gap-5">
              <div>
                <label className={labelClass} htmlFor="gate-site">
                  Gate site
                </label>
                <select
                  className={fieldClass}
                  id="gate-site"
                  onChange={(event) => setSiteId(event.target.value)}
                  value={siteId}
                >
                  <option value="">Select the operating site</option>
                  {(sitesQuery.data ?? []).filter((site) => site.is_active).map((site) => (
                    <option key={site.id} value={site.id}>
                      {site.name} · {site.gate_mode}
                    </option>
                  ))}
                </select>
              </div>
              <GateQrScanner disabled={!siteId} onError={setScanError} onScan={acceptScan} />
              {scanError ? (
                <p aria-live="assertive" className="text-sm text-red-700">
                  {scanError}
                </p>
              ) : null}
            </div>
          </div>

          <aside className="surface p-5 sm:p-6" aria-labelledby="gate-people">
            <div className="flex items-center gap-2 text-slate-950">
              <ClipboardCheck aria-hidden="true" className="h-5 w-5 text-emerald-700" />
              <h2 className="text-base font-semibold" id="gate-people">
                Registered people and visits
              </h2>
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Names come from current person and visit records, not a seeded
              scenario list. Selecting a person does not reveal or replace their QR.
            </p>
            <label className={`${labelClass} mt-5 block`} htmlFor="gate-person">
              Person and visit
            </label>
            <select
              className={fieldClass}
              id="gate-person"
              onChange={(event) => selectCandidate(event.target.value)}
              value={selectedCandidate?.visit.id ?? ""}
            >
              <option value="">Select a person</option>
              {candidates.map(({ person: candidate, visit: candidateVisit }) => (
                <option key={candidateVisit.id} value={candidateVisit.id}>
                  {candidate.first_name} {candidate.last_name} · {candidateVisit.purpose}
                </option>
              ))}
            </select>
            {selectedCandidate ? (
              <p className="mt-3 rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
                {enumLabel(selectedCandidate.person.population)} ·{" "}
                {enumLabel(selectedCandidate.visit.status)} visit ·{" "}
                {selectedCandidate.invitation
                  ? `${enumLabel(selectedCandidate.invitation.response_status)} invitation`
                  : "Invitation details restricted for this role"}
                . Scan the issued QR to continue.
              </p>
            ) : (
              <p className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                No registered people with visible visits are available.
              </p>
            )}
          </aside>
        </section>
      ) : null}

      {stage === "verify" ? (
        <section className="max-w-4xl">
          <div className="surface p-5 sm:p-6">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700">
                <ShieldCheck aria-hidden="true" className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-slate-950">
                  Verify gate presentation
                </h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  The server resolves the invitation from the issued QR. Inspect its
                  private uploads alongside the documents presented at the gate.
                </p>
              </div>
            </div>

            {presentationQuery.isPending ? (
              <p role="status" className="mt-5 text-sm text-slate-700">Checking the issued QR and loading invitee details…</p>
            ) : null}
            {presentationQuery.isError ? (
              <div role="alert" className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {errorMessage(presentationQuery.error)} No private documents can be displayed. Return to scan and try a valid issued QR.
              </div>
            ) : null}
            {presentation ? (
              <section className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4" aria-label="QR-verified invitee">
                <h3 className="font-semibold text-slate-950">{presentation.person_name}</h3>
                <p className="mt-1 text-sm text-slate-700">{presentation.email} · {presentation.company_name}</p>
                <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                  <ContextItem label="Population" value={enumLabel(presentation.population)} />
                  <ContextItem label="Purpose" value={presentation.purpose} />
                  <ContextItem label="Invited site" value={presentation.site_name} />
                  <ContextItem label="Visit window" value={`${formatDateTime(presentation.starts_at)} – ${formatDateTime(presentation.ends_at)}`} />
                  {presentation.qr_valid_from && presentation.qr_valid_until ? (
                    <ContextItem
                      label="QR entry and exit"
                      value={`${formatInSiteZone(presentation.qr_valid_from, presentation.site_timezone)} to ${formatInSiteZone(presentation.qr_valid_until, presentation.site_timezone)} · ${qrTimeLeft(presentation.qr_valid_from, presentation.qr_valid_until)}`}
                    />
                  ) : null}
                </dl>
                <p className="mt-3 text-xs text-emerald-900">These details come from the invitation linked to the scanned QR, not the selected name.</p>
              </section>
            ) : null}
            {presentation ? (
              <section className="mt-6 rounded-xl border border-slate-200 p-4" aria-label="Invitation upload comparison">
                <h3 className="font-semibold text-slate-950">Invitation uploads for physical comparison</h3>
                <p className="mt-1 text-xs leading-5 text-slate-600">Open each private upload and compare it with the original document presented by this person. Previews do not verify evidence or grant entry.</p>
                {presentation.uploads.length ? (
                  <ul className="mt-4 space-y-3">
                    {presentation.uploads.map((upload) => {
                      const key = `${upload.kind}:${upload.id ?? "invitation"}`;
                      return (
                        <li className="rounded-lg border bg-slate-50 p-3" key={key}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">{upload.label}</p>
                              <p className="text-xs text-slate-600">{upload.filename} · {enumLabel(upload.status)}</p>
                            </div>
                            <button className={secondaryButton} type="button" disabled={previewMutation.isPending} onClick={() => { setPreview(null); setComparisonConfirmed(false); previewMutation.reset(); previewMutation.mutate(upload); }}>
                              <FileSearch aria-hidden="true" className="h-4 w-4" /> Preview
                            </button>
                          </div>
                          {preview?.key === key ? (
                            <div className="mt-3 rounded-lg border bg-white p-2">
                              {preview.kind === "image" ? <img alt={`Invitation upload: ${upload.label}`} className="max-h-[32rem] max-w-full object-contain" src={preview.url} />
                                : preview.kind === "pdf" ? <iframe title={`Preview of ${upload.label}`} className="h-[32rem] w-full" src={preview.url} />
                                : <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words text-xs">{preview.text}</pre>}
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : <p className="mt-3 text-sm text-amber-800">No invitation uploads are available for comparison. Do not confirm a match.</p>}
                {previewMutation.error ? (
                  <p role="alert" className="mt-3 text-sm text-red-700">{errorMessage(previewMutation.error)}</p>
                ) : null}
                <label className="mt-5 flex items-start gap-3 text-sm text-slate-800">
                  <input type="checkbox" className="mt-1" checked={comparisonConfirmed} disabled={!presentation.uploads.length || previewMutation.isPending || evaluationMutation.isPending} onChange={(event) => setComparisonConfirmed(event.target.checked)} />
                  I have compared the invitation uploads with the physical documents presented by this invitee. This confirmation is not an entry decision.
                </label>
                {/* One request follows confirmation; the API alone decides whether entry is granted. */}
                <button
                  className={`${primaryButton} mt-4`}
                  disabled={
                    evaluationMutation.isPending ||
                    previewMutation.isPending ||
                    !siteId ||
                    !tokenReference ||
                    !comparisonConfirmed
                  }
                  onClick={evaluateGate}
                  type="button"
                >
                  <ShieldCheck aria-hidden="true" className="h-4 w-4" />
                  {evaluationMutation.isPending ? "Requesting server decision…" : "Grant Entry"}
                </button>
                <p className="mt-2 text-xs text-slate-600">
                  Entry is granted only if every backend check passes. Otherwise the
                  server returns a denial and corrective action.
                </p>
                {evaluationMutation.error ? (
                  <p role="alert" className="mt-3 text-sm text-red-700">
                    {errorMessage(evaluationMutation.error)}
                  </p>
                ) : null}
              </section>
            ) : null}
            <button className={`${secondaryButton} mt-5`} onClick={clearPresentation} type="button">
              <RotateCcw aria-hidden="true" className="h-4 w-4" />
              Return to scan
            </button>
          </div>
        </section>
      ) : null}

      {stage === "decision" && decision ? (
        <DecisionPanel
          company={company}
          decision={decision}
          person={person}
          requestedSite={requestedSite}
          visit={visit}
          onNewScan={clearPresentation}
        />
      ) : null}
    </div>
  );
}

// "opens in 25 min", "2 h 15 min left" or "expired", from the QR's own entry and exit time.
function qrTimeLeft(validFrom: string, validUntil: string): string {
  const now = Date.now();
  const describe = (ms: number) => {
    const minutes = Math.max(1, Math.round(ms / 60000));
    const hours = Math.floor(minutes / 60);
    return hours > 0 ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
  };
  if (new Date(validUntil).getTime() <= now) return "expired";
  if (new Date(validFrom).getTime() > now) return `opens in ${describe(new Date(validFrom).getTime() - now)}`;
  return `${describe(new Date(validUntil).getTime() - now)} left`;
}

function ContextItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-slate-50 p-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-1 break-words text-sm font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

// After a grant the officer can record the person leaving, the same as on the roster and for walk-ups.
function RecordExit({ visitId }: { visitId: string }) {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const exit = useMutation({
    mutationFn: () =>
      apiRequest("/api/presence/exits", { method: "POST", body: { visit_id: visitId } }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["presence"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      ]);
    }
  });
  if (!hasPermission("presence:write")) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button
        className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50"
        disabled={exit.isPending || exit.isSuccess}
        onClick={() => exit.mutate()}
        type="button"
      >
        {exit.isSuccess ? "Exit recorded" : exit.isPending ? "Recording" : "Record exit"}
      </button>
      {exit.isError ? (
        <span className="text-sm text-red-700">
          {exit.error instanceof Error ? exit.error.message : "The exit could not be recorded."}
        </span>
      ) : null}
    </div>
  );
}

function DecisionPanel({
  company,
  decision,
  person,
  requestedSite,
  visit,
  onNewScan
}: {
  company?: Company;
  decision: GateDecisionResponse;
  person?: Person;
  requestedSite?: Site;
  visit?: Visit;
  onNewScan: () => void;
}) {
  const granted = decision.decision === "GRANT";
  // These groups summarize the persisted API snapshot; they do not determine access.
  const workflowSteps = [
    {
      label: "Invitation & registration",
      codes: ["INVITATION", "VISIT"]
    },
    {
      label: "Evidence, training & compliance",
      codes: [
        "ID_CARD",
        "DRIVING_LICENCE",
        "INSURANCE_CERTIFICATE",
        "SHEQ_BASICS",
        "VLAARDINGEN_SITE_RULES",
        "LIFE_SAVING_RULES"
      ]
    },
    {
      label: "Approval & access token",
      codes: ["APPROVAL", "TOKEN"]
    },
    {
      label: "Gate identity & access",
      codes: [
        "SITE",
        "VISIT_WINDOW",
        "VISIT_STATUS",
        "PERSON_STANDING",
        "BLACKLIST",
        "IDENTITY",
        "PHYSICAL_DOCUMENT_COMPARISON"
      ]
    }
  ].map((step) => ({
    ...step,
    checks: decision.checks.filter((check) => step.codes.includes(check.code))
  }));

  return (
    <section className="space-y-6" aria-labelledby="gate-decision">
      <p aria-atomic="true" aria-live="assertive" className="sr-only" role="status">
        Server decision: {granted ? "access granted" : "access denied"}.{" "}
        {decision.primary_reason}
      </p>
      <div
        className={`rounded-2xl border p-6 shadow-soft sm:p-8 ${
          granted
            ? "border-emerald-200 bg-emerald-50"
            : "border-red-200 bg-red-50"
        }`}
      >
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-4">
            <span
              className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${
                granted ? "bg-emerald-700 text-white" : "bg-red-700 text-white"
              }`}
            >
              {granted ? (
                <CheckCircle2 aria-hidden="true" className="h-7 w-7" />
              ) : (
                <XCircle aria-hidden="true" className="h-7 w-7" />
              )}
            </span>
            <div>
              <p className="eyebrow">Backend gate decision</p>
              <h2
                className="mt-2 text-2xl font-bold tracking-tight text-slate-950"
                id="gate-decision"
              >
                {granted ? "Access granted" : "Access denied"}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-700">
                {decision.primary_reason}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone={decisionTone(decision.decision)}>
              {decision.decision}
            </StatusBadge>
            <StatusBadge tone={granted ? "success" : "danger"}>
              {decision.primary_reason_code}
            </StatusBadge>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ContextItem label="Primary result" value={decision.primary_reason} />
          <ContextItem
            label="Decision recorded at"
            value={formatDateTime(decision.occurred_at)}
          />
          <ContextItem
            label="Requested site"
            value={requestedSite?.name ?? decision.requested_site_id}
          />
          <ContextItem label="Gate event" value={decision.gate_event_id.slice(0, 13)} />
          {decision.token_valid_from && decision.token_valid_until ? (
            <ContextItem
              label="QR entry and exit"
              value={`${formatInSiteZone(decision.token_valid_from, decision.site_timezone)} to ${formatInSiteZone(decision.token_valid_until, decision.site_timezone)} · ${qrTimeLeft(decision.token_valid_from, decision.token_valid_until)}`}
            />
          ) : null}
        </div>
        {granted && decision.visit_id ? <RecordExit visitId={decision.visit_id} /> : null}

        <div
          className={`mt-6 rounded-xl border bg-white/70 p-4 ${
            granted ? "border-emerald-200" : "border-red-200"
          }`}
        >
          <div className="flex gap-3">
            {granted ? (
              <ClipboardCheck
                aria-hidden="true"
                className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700"
              />
            ) : (
              <ShieldAlert
                aria-hidden="true"
                className="mt-0.5 h-5 w-5 shrink-0 text-red-700"
              />
            )}
            <div>
              <h3
                className={
                  granted
                    ? "font-semibold text-emerald-950"
                    : "font-semibold text-red-950"
                }
              >
                {granted ? "Next operational action" : "Required corrective action"}
              </h3>
              <p
                className={
                  granted
                    ? "mt-1 text-sm leading-6 text-emerald-900"
                    : "mt-1 text-sm leading-6 text-red-900"
                }
              >
                {decision.next_action}
              </p>
            </div>
          </div>
        </div>
      </div>

      <section className="surface p-5 sm:p-6" aria-labelledby="gate-workflow-summary">
        <h3
          className="text-base font-semibold text-slate-950"
          id="gate-workflow-summary"
        >
          Invitation-to-gate workflow
        </h3>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          These results are from this gate evaluation, not earlier page progress.
          The API rechecks each requirement before recording the decision.
        </p>
        <ol className="mt-5 grid gap-3 md:grid-cols-2">
          {workflowSteps.map((step, index) => {
            const failed = step.checks.filter((check) => check.status === "failed");
            return (
              <li
                className="rounded-xl border border-slate-200 bg-slate-50 p-4"
                key={step.label}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Phase {index + 1}
                    </p>
                    <h4 className="mt-1 text-sm font-semibold text-slate-950">
                      {step.label}
                    </h4>
                  </div>
                  <StatusBadge
                    tone={
                      step.checks.length === 0
                        ? "neutral"
                        : failed.length
                          ? "danger"
                          : "success"
                    }
                  >
                    {step.checks.length === 0
                      ? "Not evaluated"
                      : failed.length
                        ? "Action required"
                        : "Passed"}
                  </StatusBadge>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-600">
                  {step.checks.length === 0
                    ? "No checks in this phase were returned for this attempt."
                    : failed.length
                      ? failed.map((check) => check.label).join(", ")
                      : `${step.checks.length} server checks passed.`}
                </p>
              </li>
            );
          })}
        </ol>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <section className="surface p-5 sm:p-6" aria-labelledby="gate-context">
          <h3 className="text-base font-semibold text-slate-950" id="gate-context">
            Gate context
          </h3>
          <dl className="mt-5 grid gap-4">
            <ContextItem
              label="Person"
              value={
                person
                  ? `${person.first_name} ${person.last_name} · ${enumLabel(person.standing)}`
                  : "No person could be resolved from this token"
              }
            />
            <ContextItem label="Company" value={company?.name ?? "Not available"} />
            <ContextItem
              label="Visit"
              value={
                visit
                  ? `${visit.purpose} · ${enumLabel(visit.status)}`
                  : "No visit could be resolved from this token"
              }
            />
            {decision.identity ? (
              <>
                <ContextItem
                  label="Identity result"
                  value={`${decision.identity.match ? "Match" : "Mismatch"} · ${decision.identity.mode}`}
                />
                <ContextItem
                  label="Identity confidence"
                  value={`${Math.round(decision.identity.confidence * 100)}% · ${decision.identity.provider_reference}`}
                />
                <StatusBadge tone="demo">
                  DEMO MODE · {decision.identity.mode}
                </StatusBadge>
              </>
            ) : null}
          </dl>
        </section>

        <section className="surface p-5 sm:p-6" aria-labelledby="server-checks">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-slate-950" id="server-checks">
                Server-evaluated checks
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Compliance and identity context is shown exactly as returned by the API.
              </p>
            </div>
            {decision.reason_codes.length > 0 ? (
              <StatusBadge tone="danger">
                {decision.reason_codes.join(", ")}
              </StatusBadge>
            ) : null}
          </div>
          <ul className="mt-5 space-y-3">
            {decision.checks.map((check) => (
              <li
                className="rounded-lg border border-slate-200 bg-white p-4"
                key={`${check.code}-${check.reason_code ?? "passed"}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-950">{check.label}</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {check.detail}
                    </p>
                  </div>
                  <StatusBadge tone={checkTone(check)}>
                    {check.status === "passed" ? "Passed" : "Failed"}
                  </StatusBadge>
                </div>
                {check.status === "failed" && check.corrective_action ? (
                  <p className="mt-3 border-l-2 border-red-300 pl-3 text-sm leading-6 text-slate-700">
                    <span className="font-semibold">Action:</span>{" "}
                    {check.corrective_action}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="flex justify-end">
        <button className={secondaryButton} onClick={onNewScan} type="button">
          <RotateCcw aria-hidden="true" className="h-4 w-4" />
          Start a new scan
        </button>
      </div>
    </section>
  );
}
