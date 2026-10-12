"use client";

import { isoToSiteInput, siteInputToIso } from "@/lib/time";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient
} from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  FileSearch,
  MailPlus,
  RefreshCw
} from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useAuth } from "@/components/auth/auth-provider";
import {
  EmptyState,
  ErrorState,
  PermissionState
} from "@/components/states/content-state";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  apiBlobRequest,
  ApiError,
  apiFormRequest,
  apiRequest
} from "@/lib/api-client";
import type {
  DemoClock,
  Evidence,
  EvidenceType,
  Invitation,
  Site
} from "@/lib/domain";
import {
  enumLabel,
  formatDateTime,
  statusTone
} from "@/lib/domain";

const fieldClass =
  "mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-emerald-600";
const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-600";
const primaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
const dangerButton =
  "inline-flex items-center justify-center rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 disabled:cursor-not-allowed disabled:opacity-50";

const invitationSchema = z
  .object({
    site_id: z.string().min(1, "Select a site."),
    invitee_email: z.string().email("Enter a valid email address."),
    population: z.enum([
      "renewi_driver",
      "temporary_driver",
      "external_driver",
      "maintenance_contractor",
      "permanent_contractor",
      "visitor"
    ]),
    company_name: z.string().min(2, "Enter a fictional company name."),
    purpose: z.string().min(3, "Describe the visit purpose."),
    starts_at: z.string().min(1, "Select a start time."),
    ends_at: z.string().min(1, "Select an end time.")
  })
  .refine((value) => new Date(siteInputToIso(value.ends_at)) > new Date(siteInputToIso(value.starts_at)), {
    message: "The end must be later than the start.",
    path: ["ends_at"]
  });

type InvitationForm = z.infer<typeof invitationSchema>;

const evidenceEditSchema = z.object({
  fields: z.string().min(2, "Enter valid JSON fields."),
  issue_date: z.string(),
  expiry_date: z.string()
});

type EvidenceEditForm = z.infer<typeof evidenceEditSchema>;

// Match the API's private-evidence limit so oversized files are rejected
// before the browser sends a multipart request.
const MAX_EVIDENCE_UPLOAD_BYTES = 5 * 1024 * 1024;

// A start rounds down, so the suggested visit has already begun and the gate accepts it right away;
// an end rounds up, so it never falls before the demo time.
function defaultDateTime(
  effectiveAt: string,
  hoursFromNow: number,
  rounding: "up" | "down" = "up"
): string {
  const step = 15 * 60 * 1000;
  const target = new Date(effectiveAt).getTime() + hoursFromNow * 60 * 60 * 1000;
  const rounded = (rounding === "down" ? Math.floor : Math.ceil)(target / step) * step;
  // The form is filled in on the site's clock (Amsterdam time).
  return isoToSiteInput(new Date(rounded).toISOString());
}

function mutationMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  // Keep locally generated validation errors visible alongside API errors.
  return error instanceof Error
    ? error.message
    : "The action could not be completed.";
}

async function invalidateWorkflow(queryClient: QueryClient, personId?: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["workflows", "invitations"] }),
    queryClient.invalidateQueries({ queryKey: ["workflows", "evidence"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "people"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "companies"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "visits"] }),
    queryClient.invalidateQueries({ queryKey: ["records", "audit-events"] }),
    ...(personId
      ? [
          queryClient.invalidateQueries({
            queryKey: ["workflows", "evidence", personId]
          })
        ]
      : [])
  ]);
}

function FormError({ message }: { message: string | null }) {
  return message ? (
    <p
      aria-live="assertive"
      className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      {message}
    </p>
  ) : null;
}

function WorkflowSteps({ invitation }: { invitation: Invitation | undefined }) {
  const registrationDone = Boolean(invitation?.person_id);
  const evidenceDone = invitation?.status === "evidence_ready";
  const steps = [
    { label: "Invitation", done: Boolean(invitation) },
    { label: "Registration", done: registrationDone },
    { label: "Evidence", done: evidenceDone }
  ];

  return (
    <ol className="grid gap-3 sm:grid-cols-3" aria-label="Invitation progress">
      {steps.map((step, index) => (
        <li
          className="surface flex items-center gap-3 p-4"
          key={step.label}
        >
          <span
            className={`grid h-8 w-8 place-items-center rounded-full text-sm font-bold ${
              step.done
                ? "bg-emerald-100 text-emerald-800"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {step.done ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
          </span>
          <div>
            <p className="text-xs text-muted-foreground">Step {index + 1}</p>
            <p className="text-sm font-semibold text-slate-950">{step.label}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

// PUBLIC_INTERFACE
/**
 * Coordinates Batch 2 forms and actions while treating API state and permissions as authoritative.
 */
export function InvitationWorkspace() {
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();
  const canCreate = hasPermission("invitations:write");
  const canReadEvidence = hasPermission("evidence:read");
  const canReviewEvidence = hasPermission("evidence:review");
  const [selectedId, setSelectedId] = useState<string>("");

  const invitationsQuery = useQuery({
    queryKey: ["workflows", "invitations"],
    queryFn: () => apiRequest<Invitation[]>("/api/invitations"),
    // Recipient responses are recorded outside this browser session.
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: false
  });
  const sitesQuery = useQuery({
    queryKey: ["records", "sites"],
    queryFn: () => apiRequest<Site[]>("/api/sites"),
    retry: false
  });

  useEffect(() => {
    if (!selectedId && invitationsQuery.data?.[0]) {
      setSelectedId(invitationsQuery.data[0].id);
    }
  }, [invitationsQuery.data, selectedId]);

  const selectedInvitation = invitationsQuery.data?.find(
    (invitation) => invitation.id === selectedId
  );

  if (invitationsQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (
    invitationsQuery.error instanceof ApiError &&
    invitationsQuery.error.status === 403
  ) {
    return <PermissionState description={invitationsQuery.error.message} />;
  }
  if (invitationsQuery.isError) {
    return (
      <ErrorState
        description={mutationMessage(invitationsQuery.error) ?? undefined}
        onRetry={() => void invitationsQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-7">
      <PageHeader
        badge={<StatusBadge tone="demo">Synthetic workflow</StatusBadge>}
        description="Send an invitation. After acceptance, the invitee submits their name and required identity document; verify both here before training and access."
        eyebrow="Steps 1–3"
        title="Invitation & evidence workspace"
      />

      <WorkflowSteps invitation={selectedInvitation} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="space-y-6">
          {canCreate ? (
            <InvitationCreatePanel
              onCreated={(invitation) => {
                queryClient.setQueryData<Invitation[]>(
                  ["workflows", "invitations"],
                  (invitations = []) => [
                    invitation,
                    ...invitations.filter(
                      (existingInvitation) =>
                        existingInvitation.id !== invitation.id
                    )
                  ]
                );
                setSelectedId(invitation.id);
                void invalidateWorkflow(queryClient);
              }}
              sites={sitesQuery.data ?? []}
            />
          ) : null}
          <InvitationList
            invitations={invitationsQuery.data ?? []}
            onSelect={setSelectedId}
            selectedId={selectedId}
          />
        </div>

        <div className="space-y-6">
          {selectedInvitation ? (
            <>
              <InvitationSummary
                invitation={selectedInvitation}
              />
              {selectedInvitation.person_id ? (
                <>
                  {selectedInvitation.registered_name ? (
                    <div className="surface p-5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                        Name submitted during registration
                      </p>
                      <p className="mt-1 text-base font-semibold text-slate-950">
                        {selectedInvitation.registered_name}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Compare this name with the uploaded identity document below.
                      </p>
                    </div>
                  ) : null}
                  <EvidencePanel
                    canRead={canReadEvidence}
                    canReview={canReviewEvidence}
                    canWrite={false}
                    invitation={selectedInvitation}
                  />
                </>
              ) : (
                <EmptyState
                  description={
                    selectedInvitation.response_status === "accepted"
                      ? "The invitee accepted. Await their name and required identity-document submission through the email registration flow."
                      : selectedInvitation.response_status === "declined"
                        ? "The invitee declined. Registration is unavailable."
                        : "Await acceptance of the emailed invitation before the invitee can register."
                  }
                  title="Awaiting invitee registration"
                />
              )}
            </>
          ) : (
            <EmptyState
              description="Create an invitation or select an existing visible invitation to continue."
              title="Select an invitation"
            />
          )}
        </div>
      </div>
    </div>
  );
}

function InvitationCreatePanel({
  sites,
  onCreated
}: {
  sites: Site[];
  onCreated: (invitation: Invitation) => void;
}) {
  const clockQuery = useQuery({
    queryKey: ["batch6", "demo-clock"],
    queryFn: () => apiRequest<DemoClock>("/api/demo-clock"),
    retry: false,
    refetchOnWindowFocus: true
  });
  const form = useForm<InvitationForm>({
    resolver: zodResolver(invitationSchema),
    defaultValues: {
      site_id: "",
      invitee_email: "",
      population: "maintenance_contractor",
      company_name: "Fictional Demo Services B.V.",
      purpose: "Scheduled maintenance support",
      starts_at: "",
      ends_at: ""
    }
  });

  // The default visit length is an administrator setting for the chosen site (8 hours if unset).
  const selectedSiteId = form.watch("site_id");
  const settingsQuery = useQuery({
    queryKey: ["site-settings"],
    queryFn: () => apiRequest<{ site_id: string; visit_default_hours: number }[]>("/api/site-settings")
  });
  const visitHours =
    settingsQuery.data?.find((row) => row.site_id === selectedSiteId)?.visit_default_hours ??
    settingsQuery.data?.[0]?.visit_default_hours ??
    8;

  useEffect(() => {
    if (!clockQuery.data) return;
    // Do not overwrite either field once the requester has chosen a visit window.
    if (!form.getFieldState("starts_at").isDirty) {
      form.setValue("starts_at", defaultDateTime(clockQuery.data.effective_at, 0, "down"));
    }
    if (!form.getFieldState("ends_at").isDirty) {
      form.setValue("ends_at", defaultDateTime(clockQuery.data.effective_at, visitHours));
    }
  }, [clockQuery.data, form, visitHours]);

  const mutation = useMutation({
    mutationFn: async (values: InvitationForm) => {
      // Re-read before submission: the saved clock may have advanced since this form loaded.
      const clock = await apiRequest<DemoClock>("/api/demo-clock");
      if (new Date(siteInputToIso(values.ends_at)).getTime() <= new Date(clock.effective_at).getTime()) {
        throw new Error("Visit end must be after the API effective demo time. Choose a later window.");
      }
      return apiRequest<Invitation>("/api/invitations", {
        method: "POST",
        body: {
          ...values,
          starts_at: siteInputToIso(values.starts_at),
          ends_at: siteInputToIso(values.ends_at)
        }
      });
    },
    onSuccess: (invitation) => {
      onCreated(invitation);
      form.reset({
        ...form.getValues(),
        invitee_email: ""
      });
    }
  });

  return (
    <section className="surface p-5" aria-labelledby="create-invitation">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
          <MailPlus className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <h2 className="font-semibold text-slate-950" id="create-invitation">
            Create invitation
          </h2>
          <p className="text-xs text-muted-foreground">
            Enter the recipient’s actual email address. Email is sent only when SMTP is configured.
          </p>
        </div>
      </div>
      <form
        className="mt-5 grid gap-4 sm:grid-cols-2"
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <label className={labelClass}>
          Site
          <select className={fieldClass} {...form.register("site_id")}>
            <option value="">Select a site</option>
            {sites
              .filter((site) => site.is_active)
              .map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
          </select>
          <span className="normal-case tracking-normal text-red-600">
            {form.formState.errors.site_id?.message}
          </span>
        </label>
        <label className={labelClass}>
          Population
          <select className={fieldClass} {...form.register("population")}>
            <option value="renewi_driver">Renewi driver</option>
            <option value="temporary_driver">Temporary driver</option>
            <option value="external_driver">External driver</option>
            <option value="maintenance_contractor">Maintenance contractor</option>
            <option value="permanent_contractor">Permanent contractor</option>
            <option value="visitor">Visitor</option>
          </select>
        </label>
        <label className={`${labelClass} sm:col-span-2`}>
          Invitee email
          <input
            autoComplete="email"
            className={fieldClass}
            type="email"
            {...form.register("invitee_email")}
          />
          <span className="normal-case tracking-normal text-red-600">
            {form.formState.errors.invitee_email?.message}
          </span>
        </label>
        <label className={`${labelClass} sm:col-span-2`}>
          Fictional company
          <input className={fieldClass} {...form.register("company_name")} />
          <span className="normal-case tracking-normal text-red-600">
            {form.formState.errors.company_name?.message}
          </span>
        </label>
        <label className={`${labelClass} sm:col-span-2`}>
          Visit purpose
          <input className={fieldClass} {...form.register("purpose")} />
          <span className="normal-case tracking-normal text-red-600">
            {form.formState.errors.purpose?.message}
          </span>
        </label>
        <label className={labelClass}>
          Starts
          <input
            className={fieldClass}
            type="datetime-local"
            {...form.register("starts_at")}
          />
        </label>
        <label className={labelClass}>
          Ends
          <input
            className={fieldClass}
            type="datetime-local"
            {...form.register("ends_at")}
          />
          <span className="normal-case tracking-normal text-red-600">
            {form.formState.errors.ends_at?.message}
          </span>
        </label>
        <div className="space-y-3 sm:col-span-2">
          {clockQuery.isError ? (
            <p role="alert" className="text-sm text-red-700">
              The API effective demo time is unavailable. Reload the invitation form before scheduling a visit.
            </p>
          ) : clockQuery.data ? (
            <p className="text-xs text-muted-foreground">
              Suggested window is based on API effective demo time: {formatDateTime(clockQuery.data.effective_at)}.
              You can edit the visit dates; the API validates the final window.
            </p>
          ) : null}
          <FormError message={mutationMessage(mutation.error)} />
          <button className={primaryButton} disabled={mutation.isPending || !clockQuery.data} type="submit">
            {mutation.isPending ? "Creating…" : "Create and send invitation"}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </form>
    </section>
  );
}

function InvitationList({
  invitations,
  selectedId,
  onSelect
}: {
  invitations: Invitation[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="surface p-5" aria-labelledby="visible-invitations">
      <h2 className="font-semibold text-slate-950" id="visible-invitations">
        Visible invitations
      </h2>
      <p className="mt-1 text-xs text-muted-foreground">
        The API filters this list to the signed-in account’s object scope.
      </p>
      {invitations.length === 0 ? (
        <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-muted-foreground">
          No invitations are visible to this role yet.
        </p>
      ) : (
        // Only the cards scroll; the section heading and scope note stay visible.
        <div
          aria-label="Visible invitations list"
          className="mt-4 max-h-96 space-y-2 overflow-y-auto overscroll-contain pr-2"
          role="region"
          tabIndex={0}
        >
          {invitations.map((invitation) => (
            <button
              aria-pressed={selectedId === invitation.id}
              className={`w-full rounded-xl border p-4 text-left transition ${
                selectedId === invitation.id
                  ? "border-emerald-500 bg-emerald-50/60"
                  : "bg-white hover:bg-slate-50"
              }`}
              key={invitation.id}
              onClick={() => onSelect(invitation.id)}
              type="button"
            >
              <span className="flex items-start justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-950">
                    {invitation.invitee_email}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {invitation.company_name}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Response: {enumLabel(invitation.response_status)}
                  </span>
                </span>
                <StatusBadge tone={statusTone(invitation.status)}>
                  {enumLabel(invitation.status)}
                </StatusBadge>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function InvitationSummary({ invitation }: { invitation: Invitation }) {
  return (
    <section className="surface p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="eyebrow">{enumLabel(invitation.population)}</p>
          <h2 className="mt-2 text-lg font-semibold text-slate-950">
            {invitation.invitee_email}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {invitation.company_name} · {invitation.purpose}
          </p>
        </div>
        <StatusBadge tone={statusTone(invitation.status)}>
          {enumLabel(invitation.status)}
        </StatusBadge>
      </div>
      <p className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        {invitation.person_id
          ? invitation.registered_name
            ? `Invitee-submitted name: ${invitation.registered_name} · ${invitation.invitee_email}. Compare this name with the uploaded document before verifying evidence.`
            : "A person is linked to this invitation. Their name is not available to this account."
          : "Recipient email only — no person or visit is linked yet. The invitee completes registration after accepting."}
      </p>
      <dl className="mt-5 grid gap-4 border-t pt-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Recipient response
          </dt>
          <dd className="mt-1 text-slate-900">
            {enumLabel(invitation.response_status)}
            {invitation.responded_at
              ? ` · ${formatDateTime(invitation.responded_at)}`
              : ""}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Invitee registration
          </dt>
          <dd className="mt-1 text-slate-900">
            {invitation.registration_completed_at
              ? `Submitted · ${formatDateTime(invitation.registration_completed_at)}`
              : "Awaiting invitee submission"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Invitation delivery
          </dt>
          <dd className="mt-1 text-slate-900">
            {invitation.delivery_status === "smtp_sent"
              ? "Handed to SMTP (inbox delivery not guaranteed)"
              : invitation.delivery_status === "smtp_failed"
                ? "SMTP handoff failed"
                : "Local only — no email sent"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Visit window
          </dt>
          <dd className="mt-1 text-slate-900">
            {formatDateTime(invitation.starts_at)} – {formatDateTime(invitation.ends_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Workflow reference
          </dt>
          <dd className="mt-1 font-mono text-xs text-slate-700">
            {invitation.id}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function EvidencePanel({
  invitation,
  canRead,
  canWrite,
  canReview
}: {
  invitation: Invitation;
  canRead: boolean;
  canWrite: boolean;
  canReview: boolean;
}) {
  const queryClient = useQueryClient();
  // Identity uploads must match the invitation population; certificates remain optional choices.
  const requiredIdentityType: EvidenceType = [
    "renewi_driver",
    "temporary_driver",
    "external_driver"
  ].includes(invitation.population)
    ? "driving_licence"
    : "id_card";
  const [uploadType, setUploadType] = useState<EvidenceType>(requiredIdentityType);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [showExistingEvidence, setShowExistingEvidence] = useState(true);
  const [uploadInputKey, setUploadInputKey] = useState(0);
  const personId = invitation.person_id as string;

  useEffect(() => {
    setUploadType(requiredIdentityType);
    setUploadFile(null);
    setUploadError(null);
    setShowExistingEvidence(true);
    setUploadInputKey((value) => value + 1);
  }, [invitation.id, requiredIdentityType]);

  const evidenceQuery = useQuery({
    queryKey: ["workflows", "evidence", personId],
    queryFn: () =>
      apiRequest<Evidence[]>(`/api/people/${personId}/evidence`),
    enabled: canRead,
    retry: false
  });
  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!uploadFile) {
        throw new Error("Choose a visibly synthetic file.");
      }
      if (uploadFile.size === 0 || uploadFile.size > MAX_EVIDENCE_UPLOAD_BYTES) {
        throw new Error("Upload must contain between 1 byte and 5 MiB.");
      }
      const formData = new FormData();
      formData.set("evidence_type", uploadType);
      formData.set("file", uploadFile);
      return apiFormRequest<Evidence>(
        `/api/invitations/${invitation.id}/evidence/uploads`,
        formData,
        { method: "POST" }
      );
    },
    onSuccess: (record) => {
      setUploadFile(null);
      setUploadError(null);
      setUploadInputKey((value) => value + 1);
      // The upload response already contains the server-owned person/invitation link.
      queryClient.setQueryData<Evidence[]>(
        ["workflows", "evidence", personId],
        (records = []) => [record, ...records.filter((item) => item.id !== record.id)]
      );
      setShowExistingEvidence(true);
      void invalidateWorkflow(queryClient, personId);
    }
  });

  if (!canRead) {
    return (
      <PermissionState
        description="Registration is complete, but this role cannot read private evidence metadata."
        title="Evidence is restricted"
      />
    );
  }
  if (evidenceQuery.isLoading) {
    return <PageSkeleton />;
  }
  if (evidenceQuery.isError) {
    return (
      <ErrorState
        description={mutationMessage(evidenceQuery.error) ?? undefined}
        onRetry={() => void evidenceQuery.refetch()}
      />
    );
  }

  const evidence = evidenceQuery.data ?? [];
  return (
    <section className="space-y-5" aria-labelledby="evidence-workspace">
      <div className="surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-950" id="evidence-workspace">
              Private evidence
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Select an evidence type and upload one private document. The
              backend prepares it for review below.
            </p>
          </div>
          <StatusBadge tone={evidence.length ? "info" : "neutral"}>
            {evidence.length} record{evidence.length === 1 ? "" : "s"}
          </StatusBadge>
        </div>

        {canWrite ? (
          <div className="mt-5 border-t pt-5">
            <div className="rounded-xl border bg-slate-50/60 p-4">
              <p className="text-sm font-semibold text-slate-950">
                Upload evidence
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {requiredIdentityType === "driving_licence"
                  ? "Drivers: upload a driving licence, not an ID card."
                  : "Non-drivers: upload an ID card, not a driving licence."}
                {" "}The document must be verified and current before compliance can pass.
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className={labelClass}>
                  Evidence type
                  <select
                    className={fieldClass}
                    onChange={(event) =>
                      setUploadType(event.target.value as EvidenceType)
                    }
                    value={uploadType}
                  >
                    <option value={requiredIdentityType}>
                      {requiredIdentityType === "driving_licence" ? "Driving licence" : "ID card"}
                    </option>
                    <option value="vca_certificate">VCA certificate</option>
                    <option value="insurance_certificate">
                      Insurance certificate
                    </option>
                  </select>
                </label>
                <label className={labelClass}>
                  Document file
                  <input
                    className="mt-1.5 block w-full text-xs text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2 file:font-semibold"
                    key={uploadInputKey}
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null;
                      // Dismiss previously viewed documents as soon as a new
                      // file is selected; never alter their stored records.
                      if (file) setShowExistingEvidence(false);
                      setUploadError(
                        file && (file.size === 0 || file.size > MAX_EVIDENCE_UPLOAD_BYTES)
                          ? "Upload must contain between 1 byte and 5 MiB."
                          : null
                      );
                      setUploadFile(
                        file && file.size > 0 && file.size <= MAX_EVIDENCE_UPLOAD_BYTES
                          ? file
                          : null
                      );
                      uploadMutation.reset();
                    }}
                    type="file"
                  />
                </label>
              </div>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-muted-foreground">
                  Select any file format; the API accepts supported formats up
                  to 5 MiB. Synthetic demo files must include a visible DEMO
                  marker.
                </p>
                <button
                  className={primaryButton}
                  disabled={!uploadFile || uploadMutation.isPending}
                  onClick={() => uploadMutation.mutate()}
                  type="button"
                >
                  {uploadMutation.isPending ? "Uploading…" : "Upload"}
                </button>
              </div>
              <FormError message={uploadError ?? mutationMessage(uploadMutation.error)} />
            </div>
          </div>
        ) : null}
      </div>

      {!showExistingEvidence ? (
        <EmptyState
          description="Previously viewed evidence is hidden until a new upload succeeds."
          title="Awaiting new evidence"
        />
      ) : evidence.length === 0 ? (
        <EmptyState
          description="Select an evidence type and upload a document to begin review."
          title="No evidence has been attached"
        />
      ) : (
        <div className="grid gap-4">
          {evidence.map((record) => (
            <EvidenceCard
              canReview={canReview}
              evidence={record}
              key={record.id}
              onChanged={async (updatedEvidence) => {
                await invalidateWorkflow(queryClient, record.person_id);
                if (updatedEvidence.status === "verified") {
                  queryClient.setQueryData<Invitation[]>(
                    ["workflows", "invitations"],
                    (invitations) =>
                      invitations?.map((item) =>
                        item.id === invitation.id
                          ? { ...item, status: "evidence_ready" }
                          : item
                      )
                  );
                }
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function EvidenceCard({
  evidence,
  canReview,
  onChanged
}: {
  evidence: Evidence;
  canReview: boolean;
  onChanged: (updatedEvidence: Evidence) => Promise<void>;
}) {
  const [reason, setReason] = useState("Reviewed against the synthetic demo document.");
  const [preview, setPreview] = useState<{
    evidenceId: string;
    contentHash: string;
    kind: "pdf" | "image" | "text";
    url?: string;
    text?: string;
  } | null>(null);
  const [previewNotice, setPreviewNotice] = useState<string | null>(null);
  const previewed = preview?.evidenceId === evidence.id &&
    preview.contentHash === evidence.content_sha256;

  useEffect(() => {
    // Private object URLs should not survive a change of evidence or unmount.
    return () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  const previewMutation = useMutation({
    mutationFn: () => apiBlobRequest(`/api/evidence/${evidence.id}/content`),
    onSuccess: async (blob) => {
      const type = evidence.media_type.toLowerCase();
      const kind =
        type === "application/pdf" ? "pdf" :
        ["image/png", "image/jpeg", "image/gif", "image/webp"].includes(type) ? "image" :
        ["text/plain", "application/json"].includes(type) ? "text" : null;
      if (!kind) {
        setPreview(null);
        setPreviewNotice("This file format cannot be previewed safely in the browser. It has not been verified.");
        return;
      }
      if (kind === "text") {
        const text = await blob.text();
        setPreview({ evidenceId: evidence.id, contentHash: evidence.content_sha256, kind, text });
      } else {
        // Use the known evidence MIME rather than trusting an arbitrary upload response.
        const url = URL.createObjectURL(new Blob([blob], { type }));
        setPreview({ evidenceId: evidence.id, contentHash: evidence.content_sha256, kind, url });
      }
      setPreviewNotice(null);
    }
  });
  const reviewMutation = useMutation({
    mutationFn: (action: "verify" | "reject" | "request-reupload") =>
      apiRequest<Evidence>(`/api/evidence/${evidence.id}/${action}`, {
        method: "POST",
        body: { reason }
      }),
    onSuccess: onChanged
  });
  const editForm = useForm<EvidenceEditForm>({
    resolver: zodResolver(evidenceEditSchema),
    defaultValues: {
      fields: JSON.stringify(evidence.extracted_fields, null, 2),
      issue_date: evidence.issue_date ?? "",
      expiry_date: evidence.expiry_date ?? ""
    }
  });
  useEffect(() => {
    editForm.reset({
      fields: JSON.stringify(evidence.extracted_fields, null, 2),
      issue_date: evidence.issue_date ?? "",
      expiry_date: evidence.expiry_date ?? ""
    });
  }, [editForm, evidence]);
  const editMutation = useMutation({
    mutationFn: (values: EvidenceEditForm) => {
      let fields: Record<string, unknown>;
      try {
        fields = JSON.parse(values.fields) as Record<string, unknown>;
      } catch {
        throw new Error("Extracted fields must be valid JSON.");
      }
      return apiRequest<Evidence>(`/api/evidence/${evidence.id}/fields`, {
        method: "PATCH",
        body: {
          fields,
          issue_date: values.issue_date || null,
          expiry_date: values.expiry_date || null
        }
      });
    },
    onSuccess: onChanged
  });
  const error =
    previewMutation.error ??
    editMutation.error ??
    reviewMutation.error;
  const busy =
    previewMutation.isPending ||
    editMutation.isPending ||
    reviewMutation.isPending;
  const licenceAssessment =
    evidence.evidence_type === "driving_licence"
      ? evidence.validity_assessment
      : undefined;
  const assessmentStatus = licenceAssessment?.assessment_status;
  const assessmentChecks =
    licenceAssessment?.checks &&
    typeof licenceAssessment.checks === "object" &&
    !Array.isArray(licenceAssessment.checks)
      ? Object.entries(licenceAssessment.checks)
      : [];
  const assessmentTone =
    assessmentStatus === "appears_valid"
      ? "success"
      : assessmentStatus === "appears_expired"
        ? "danger"
        : "warning";

  return (
    <article className="surface p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-950">
            {enumLabel(evidence.evidence_type)}
          </p>
          <p className="mt-1 break-all text-xs text-muted-foreground">
            {evidence.filename} · {(evidence.size_bytes / 1024).toFixed(1)} KiB
          </p>
          {["id_card", "driving_licence"].includes(evidence.evidence_type) ? (
            <p className="mt-2 text-sm text-slate-700">
              ID expiry date: {evidence.expiry_date ?? "Not recorded"}
              {evidence.status !== "verified" ? " · Not verified" : ""}
            </p>
          ) : null}
        </div>
        <StatusBadge tone={statusTone(evidence.status)}>
          {enumLabel(evidence.status)}
        </StatusBadge>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className={secondaryButton}
          disabled={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
          type="button"
        >
          <FileSearch className="h-4 w-4" aria-hidden="true" />
          {previewMutation.isPending ? "Loading preview…" : "Preview"}
        </button>
      </div>

      {previewNotice ? (
        <p role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          {previewNotice}
        </p>
      ) : null}
      {previewed ? (
        <section className="mt-4 rounded-xl border p-3" aria-label={`Preview of ${evidence.filename}`}>
          <p className="mb-3 text-sm font-semibold text-slate-950">Preview: {evidence.filename}</p>
          {preview.kind === "image" ? (
            <img alt={`Uploaded evidence: ${evidence.filename}`} className="max-h-[32rem] max-w-full object-contain" src={preview.url} />
          ) : preview.kind === "pdf" ? (
            <iframe title={`Preview of ${evidence.filename}`} className="h-[32rem] w-full" src={preview.url} />
          ) : (
            <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs">{preview.text}</pre>
          )}
        </section>
      ) : null}

      {licenceAssessment && assessmentStatus ? (
        <section
          aria-labelledby={`licence-assessment-${evidence.id}`}
          className="mt-5 rounded-xl border border-slate-200 bg-slate-50/70 p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3
                className="text-sm font-semibold text-slate-950"
                id={`licence-assessment-${evidence.id}`}
              >
                Netherlands driving-licence assessment
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                AI-assisted extraction is shown for gatekeeper review only.
              </p>
            </div>
            <StatusBadge tone={assessmentTone}>
              {enumLabel(assessmentStatus)}
            </StatusBadge>
          </div>

          {licenceAssessment.summary ? (
            <p className="mt-3 text-sm leading-6 text-slate-800">
              {licenceAssessment.summary}
            </p>
          ) : null}

          {Object.keys(evidence.extracted_fields).length > 0 ? (
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              {Object.entries(evidence.extracted_fields).map(([key, value]) => (
                <div className="rounded-lg border bg-white p-3" key={key}>
                  <dt className="text-xs font-semibold uppercase text-muted-foreground">
                    {enumLabel(key)}
                  </dt>
                  <dd className="mt-1 break-words text-sm text-slate-900">
                    {Array.isArray(value) ? value.join(", ") : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          {assessmentChecks.length > 0 ? (
            <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
              {assessmentChecks.map(([key, value]) => (
                <div className="flex justify-between gap-3 rounded-md bg-white px-3 py-2" key={key}>
                  <dt className="font-semibold text-slate-700">{enumLabel(key)}</dt>
                  <dd className="text-right text-slate-600">
                    {Array.isArray(value)
                      ? value.length > 0
                        ? value.map((item) => enumLabel(String(item))).join(", ")
                        : "None"
                      : value === true
                        ? "Yes"
                        : value === false
                          ? "No"
                          : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
            This assessment does not authenticate the document, approve evidence,
            or grant site access. A gatekeeper must inspect the document and
            explicitly select <strong>Verify evidence</strong>.
          </p>
        </section>
      ) : null}

      {evidence.status === "extracted" && canReview ? (
        <form
          className="mt-5 grid gap-4 border-t pt-5"
          onSubmit={editForm.handleSubmit((values) => editMutation.mutate(values))}
        >
          <label className={labelClass}>
            Editable extracted fields (JSON)
            <textarea
              className={`${fieldClass} min-h-40 font-mono text-xs`}
              {...editForm.register("fields")}
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={labelClass}>
              Issue date
              <input
                className={fieldClass}
                type="date"
                {...editForm.register("issue_date")}
              />
            </label>
            <label className={labelClass}>
              Expiry date
              <input
                className={fieldClass}
                type="date"
                {...editForm.register("expiry_date")}
              />
            </label>
          </div>
          <button className={secondaryButton} disabled={busy} type="submit">
            Save reviewed fields
          </button>
        </form>
      ) : Object.keys(evidence.extracted_fields).length > 0 ? (
        <dl className="mt-5 grid gap-3 border-t pt-5 sm:grid-cols-2">
          {Object.entries(evidence.extracted_fields).map(([key, value]) => (
            <div className="rounded-lg bg-slate-50 p-3" key={key}>
              <dt className="text-xs font-semibold uppercase text-muted-foreground">
                {enumLabel(key)}
              </dt>
              <dd className="mt-1 break-words text-sm text-slate-900">
                {Array.isArray(value) ? value.join(", ") : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {canReview && evidence.status !== "superseded" ? (
        <div className="mt-5 space-y-3 border-t pt-5">
          <label className={labelClass}>
            Decision reason
            <textarea
              className={`${fieldClass} min-h-20`}
              onChange={(event) => setReason(event.target.value)}
              value={reason}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              className={primaryButton}
              disabled={busy || !previewed || !["uploaded", "extracted"].includes(evidence.status) || reason.trim().length < 3}
              onClick={() => reviewMutation.mutate("verify")}
              type="button"
            >
              Verify evidence
            </button>
            <button
              className={dangerButton}
              disabled={busy || reason.length < 3}
              onClick={() => reviewMutation.mutate("reject")}
              type="button"
            >
              Reject
            </button>
            <button
              className={secondaryButton}
              disabled={busy || reason.length < 3}
              onClick={() => reviewMutation.mutate("request-reupload")}
              type="button"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Request re-upload
            </button>
          </div>
          {!previewed && ["uploaded", "extracted"].includes(evidence.status) ? (
            <p className="text-xs text-muted-foreground">Preview this document before manually verifying its details.</p>
          ) : null}
        </div>
      ) : null}

      {evidence.review_notes ? (
        <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
          <strong>Latest review:</strong> {evidence.review_notes}
        </p>
      ) : null}
      <FormError message={mutationMessage(error)} />
    </article>
  );
}
