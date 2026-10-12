"use client";

import { SITE_TIME_ZONE } from "@/lib/time";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Building2,
  CheckCircle2,
  Clock3,
  Files,
  LogOut,
  MapPin,
  ShieldAlert,
  UsersRound
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState, ErrorState } from "@/components/states/content-state";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import type {
  CurrentPresence,
  DashboardByPath,
  DashboardPathCounts,
  DashboardDecision,
  DashboardSite,
  DashboardSnapshot,
  Evidence,
  Invitation,
  Person,
  PresenceEvent
} from "@/lib/domain";
import { enumLabel, formatDateTime } from "@/lib/domain";

const fieldClass =
  "mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-emerald-600";
const actionButton =
  "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The operational data could not be loaded.";
}

function decisionTone(decision: DashboardDecision["decision"]): StatusTone {
  return decision === "GRANT" ? "success" : "danger";
}

// People on site, entered and exited, split into planned (invited) and unexpected (walk-up) arrivals.
function PathBreakdown({ byPath }: { byPath?: DashboardByPath | null }) {
  if (!byPath) return null;
  const rows: { label: string; key: keyof DashboardPathCounts }[] = [
    { label: "On site now", key: "present_count" },
    { label: "Entered", key: "entry_count" },
    { label: "Exited", key: "exit_count" },
    { label: "Turned away or denied", key: "denial_count" },
    { label: "Overdue (still on site after their exit time)", key: "overdue_count" }
  ];
  return (
    <section aria-labelledby="path-breakdown" className="surface overflow-hidden">
      <div className="border-b border-slate-200 px-5 py-4">
        <h3 className="text-base font-semibold text-slate-950" id="path-breakdown">
          Planned and unexpected arrivals
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Planned people were invited and approved in advance. Unexpected people turned up without
          an invitation and registered themselves at the entrance QR.
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-5 py-3 font-semibold" scope="col"></th>
            <th className="px-5 py-3 font-semibold" scope="col">Planned: invited in advance</th>
            <th className="px-5 py-3 font-semibold" scope="col">Unexpected: walk-up arrivals</th>
            <th className="px-5 py-3 font-semibold" scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-t border-slate-100" key={row.key}>
              <th className="px-5 py-3 text-left font-medium text-slate-700" scope="row">
                {row.label}
              </th>
              <td className="px-5 py-3 font-semibold text-slate-950">{byPath.planned[row.key] ?? 0}</td>
              <td className="px-5 py-3 font-semibold text-slate-950">{byPath.walk_up[row.key] ?? 0}</td>
              <td className="px-5 py-3 font-semibold text-slate-950">
                {(byPath.planned[row.key] ?? 0) + (byPath.walk_up[row.key] ?? 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const LIVE_REFRESH_MS = 15_000;

// "45 min" or "2 h 10 min".
function formatOverdue(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

function MetricCard({
  icon: Icon,
  label,
  value,
  tone = "emerald"
}: {
  icon: typeof UsersRound;
  label: string;
  value: number;
  tone?: "emerald" | "blue" | "amber" | "red";
}) {
  const iconClasses = {
    emerald: "bg-emerald-50 text-emerald-700",
    blue: "bg-blue-50 text-blue-700",
    amber: "bg-amber-50 text-amber-700",
    red: "bg-red-50 text-red-700"
  }[tone];

  return (
    <article className="surface p-4">
      <div className="flex items-center gap-3">
        <span className={`grid h-10 w-10 place-items-center rounded-xl ${iconClasses}`}>
          <Icon aria-hidden="true" className="h-5 w-5" />
        </span>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <p className="mt-1 text-2xl font-bold tracking-tight text-slate-950">
            {new Intl.NumberFormat().format(value)}
          </p>
        </div>
      </div>
    </article>
  );
}

function SiteMetrics({ site }: { site: DashboardSite }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-slate-950">{site.site_name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{site.country_code}</p>
        </div>
        <StatusBadge tone={site.present_count > 0 ? "success" : "neutral"}>
          {site.present_count} on site
        </StatusBadge>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-slate-500">Active visits</dt>
          <dd className="mt-1 font-semibold text-slate-950">{site.active_visit_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Grants</dt>
          <dd className="mt-1 font-semibold text-emerald-700">{site.grant_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Denials</dt>
          <dd className="mt-1 font-semibold text-red-700">{site.denial_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Entries</dt>
          <dd className="mt-1 font-semibold text-slate-950">{site.entry_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Exits</dt>
          <dd className="mt-1 font-semibold text-slate-950">{site.exit_count}</dd>
        </div>
      </dl>
    </article>
  );
}

function RosterTable({
  canRecordExit,
  isRecordingExit,
  people,
  onRecordExit
}: {
  canRecordExit: boolean;
  isRecordingExit: boolean;
  people: CurrentPresence[];
  onRecordExit: (person: CurrentPresence) => void;
}) {
  if (people.length === 0) {
    return (
      <EmptyState
        className="border-dashed shadow-none"
        description="The backend projection has no current authorized entries for this site."
        title="No one is currently on site"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[45rem] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3 font-semibold">Person</th>
            <th className="px-4 py-3 font-semibold">Population</th>
            <th className="px-4 py-3 font-semibold">Entry recorded</th>
            <th className="px-4 py-3 font-semibold">Exit by</th>
            <th className="px-4 py-3 font-semibold">Authoritative status</th>
            {canRecordExit ? <th className="px-4 py-3 font-semibold">Action</th> : null}
          </tr>
        </thead>
        <tbody>
          {people.map((person) => (
            <tr
              className={`border-b border-slate-100 last:border-0 ${person.overdue ? "bg-amber-50" : ""}`}
              key={person.visit_id ?? person.walk_up_registration_id ?? person.person_id}
            >
              <td className="px-4 py-4">
                <span className="font-semibold text-slate-950">{person.person_name}</span>
                {person.source === "walk_up" ? (
                  <span className="mt-1 block text-xs font-normal text-slate-600">
                    Walk-up arrival, registered at the entrance QR
                  </span>
                ) : (
                  <span className="mt-1 block text-xs font-normal text-slate-600">
                    Verified ID expiry: {person.id_expiry_date ?? "Not available"}
                  </span>
                )}
              </td>
              <td className="px-4 py-4 text-slate-700">{enumLabel(person.population)}</td>
              <td className="px-4 py-4 text-slate-700">{formatDateTime(person.entered_at)}</td>
              <td className="px-4 py-4 text-slate-700">
                {person.exit_due_at || person.visit_ends_at
                  ? formatDateTime((person.exit_due_at ?? person.visit_ends_at) as string)
                  : "No exit time recorded"}
              </td>
              <td className="px-4 py-4">
                <StatusBadge tone="success">{person.decision}</StatusBadge>
                {person.overdue ? (
                  <span className="mt-1 block">
                    <StatusBadge tone="warning">
                      Overdue{person.overdue_minutes ? ` by ${formatOverdue(person.overdue_minutes)}` : ""}
                    </StatusBadge>
                    {person.exit_due_at ? (
                      <span className="mt-1 block text-xs text-amber-900">
                        Should have left by {formatDateTime(person.exit_due_at)}
                      </span>
                    ) : null}
                  </span>
                ) : null}
              </td>
              {canRecordExit ? (
                <td className="px-4 py-4">
                  <button
                    className={actionButton}
                    disabled={isRecordingExit}
                    onClick={() => onRecordExit(person)}
                    type="button"
                  >
                    <LogOut aria-hidden="true" className="h-4 w-4" />
                    Record exit
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UploadedEvidence({ siteId }: { siteId: string }) {
  const { hasPermission } = useAuth();
  const canRead = hasPermission("invitations:read") && hasPermission("evidence:read");
  const canReadPeople = hasPermission("people:read");
  const invitationsQuery = useQuery({
    queryKey: ["workflows", "invitations"],
    queryFn: () => apiRequest<Invitation[]>("/api/invitations"),
    enabled: canRead,
    retry: false
  });
  const peopleQuery = useQuery({
    queryKey: ["records", "people"],
    queryFn: () => apiRequest<Person[]>("/api/people"),
    enabled: canRead && canReadPeople,
    retry: false
  });
  const invitations = useMemo(
    () => (invitationsQuery.data ?? []).filter(
      (invitation) => invitation.person_id && (!siteId || invitation.site_id === siteId)
    ),
    [invitationsQuery.data, siteId]
  );
  const personIds = useMemo(
    () => Array.from(new Set(invitations.map((invitation) => invitation.person_id as string))).sort(),
    [invitations]
  );
  const evidenceQuery = useQuery({
    queryKey: ["dashboard", "uploaded-evidence", personIds],
    queryFn: async () => {
      // Read only evidence for backend-linked people; the API checks each person's scope.
      const records = await Promise.all(
        personIds.map(async (personId) => ({
          personId,
          evidence: await apiRequest<Evidence[]>(`/api/people/${personId}/evidence`)
        }))
      );
      return records;
    },
    enabled: canRead && invitationsQuery.isSuccess && personIds.length > 0,
    retry: false
  });

  if (!canRead) {
    return null;
  }

  const error = invitationsQuery.error ?? peopleQuery.error ?? evidenceQuery.error;
  const records = (evidenceQuery.data ?? []).flatMap(({ personId, evidence }) =>
    evidence
      .filter((item) => item.status !== "superseded")
      .map((item) => ({
        item,
        invitation: invitations.find(
          (candidate) => candidate.id === item.invitation_id && candidate.person_id === personId
        )
      }))
      .filter((entry) => entry.invitation)
  );

  return (
    <section className="surface p-5" aria-labelledby="dashboard-uploaded-evidence">
      <div className="flex items-center gap-2">
        <Files aria-hidden="true" className="h-5 w-5 text-emerald-700" />
        <h3 className="font-semibold text-slate-950" id="dashboard-uploaded-evidence">
          Uploaded documents
        </h3>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Private evidence linked by the API to visible registered invitations.
        Presence does not mean verified or approved.
      </p>
      {error ? (
        <ErrorState
          className="mt-4"
          description={errorMessage(error)}
          onRetry={() => {
            void invitationsQuery.refetch();
            if (canReadPeople) void peopleQuery.refetch();
            void evidenceQuery.refetch();
          }}
          title="Uploaded documents could not be loaded"
        />
      ) : invitationsQuery.isLoading || evidenceQuery.isLoading ? (
        <div className="mt-4"><PageSkeleton /></div>
      ) : records.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">
          No uploaded documents are linked to visible invitations for this site.
        </p>
      ) : (
        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {records.map(({ item, invitation }) => {
            const person = peopleQuery.data?.find((candidate) => candidate.id === item.person_id);
            const label = person
              ? `${person.first_name} ${person.last_name}`
              : invitation?.invitee_email ?? "Registered person";
            return (
              <li className="rounded-xl border bg-slate-50/60 p-4" key={item.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-slate-950">{label}</p>
                    <p className="mt-1 break-all text-xs text-slate-600">
                      {item.filename} · {enumLabel(item.evidence_type)}
                    </p>
                  </div>
                  <StatusBadge tone={item.status === "verified" ? "success" : "info"}>
                    {enumLabel(item.status)}
                  </StatusBadge>
                </div>
                <Link
                  className="mt-3 inline-block text-sm font-semibold text-emerald-800 hover:text-emerald-950"
                  href={canReadPeople ? `/people/${item.person_id}` : "/invitations"}
                >
                  View document details
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// PUBLIC_INTERFACE
/**
 * Renders the Batch 5 backend-authoritative operational dashboard and on-site
 * roster. The component only displays safe API projections; it never computes
 * presence, gate outcomes, or occupancy counters in the browser.
 */
export function OperationalDashboard() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [selectedSiteId, setSelectedSiteId] = useState("");
  const [exitConfirmation, setExitConfirmation] = useState<string | null>(null);

  const dashboardQuery = useQuery({
    queryKey: ["dashboard", "snapshot"],
    queryFn: () => apiRequest<DashboardSnapshot>("/api/dashboard?activity_hours=24&recent_limit=20"),
    enabled: hasPermission("dashboard:read"),
    retry: false,
    // Live view: the numbers refresh on their own so a manager watching sees people arrive and leave.
    refetchInterval: LIVE_REFRESH_MS,
    refetchIntervalInBackground: false
  });
  const presenceQuery = useQuery({
    queryKey: ["presence", selectedSiteId || "all"],
    queryFn: () =>
      apiRequest<CurrentPresence[]>(
        selectedSiteId ? `/api/presence?site_id=${encodeURIComponent(selectedSiteId)}` : "/api/presence"
      ),
    enabled: hasPermission("presence:read"),
    retry: false,
    refetchInterval: LIVE_REFRESH_MS,
    refetchIntervalInBackground: false
  });

  useEffect(() => {
    if (!selectedSiteId && dashboardQuery.data?.sites.length === 1) {
      setSelectedSiteId(dashboardQuery.data.sites[0].site_id);
    }
  }, [dashboardQuery.data?.sites, selectedSiteId]);

  const exitMutation = useMutation({
    mutationFn: async (person: CurrentPresence) => {
      if (person.source === "walk_up" && person.walk_up_registration_id && person.site_key) {
        // A walk-up person has no visit: the exit is recorded on their arrival.
        await apiRequest("/api/walk-up/gate/exit", {
          method: "POST",
          body: { site_key: person.site_key, registration_id: person.walk_up_registration_id }
        });
        return { walkUpRegistrationId: person.walk_up_registration_id, name: person.person_name } as const;
      }
      const event = await apiRequest<PresenceEvent>("/api/presence/exits", {
        method: "POST",
        body: { visit_id: person.visit_id }
      });
      return { event } as const;
    },
    onMutate: () => setExitConfirmation(null),
    onSuccess: async (result) => {
      if ("walkUpRegistrationId" in result) {
        queryClient.setQueriesData<CurrentPresence[]>(
          { queryKey: ["presence"] },
          (people) => people?.filter((person) => person.walk_up_registration_id !== result.walkUpRegistrationId)
        );
      } else if (result.event.event_type === "exit") {
        // Only a committed exit may remove a row; retain every other visit in
        // both the selected-site and all-sites roster caches.
        queryClient.setQueriesData<CurrentPresence[]>(
          { queryKey: ["presence"] },
          (people) => people?.filter((person) => person.visit_id !== result.event.visit_id)
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["presence"] }),
        queryClient.invalidateQueries({ queryKey: ["walk-up"] })
      ]);
      setExitConfirmation(
        "walkUpRegistrationId" in result
          ? `The exit for ${result.name} was recorded. The roster has been refreshed.`
          : `The API recorded the exit for visit ${result.event.visit_id.slice(0, 8)}. The roster has been refreshed.`
      );
    }
  });

  const filteredSites = useMemo(() => {
    const sites = dashboardQuery.data?.sites ?? [];
    return selectedSiteId ? sites.filter((site) => site.site_id === selectedSiteId) : sites;
  }, [dashboardQuery.data?.sites, selectedSiteId]);

  const recentDecisions = useMemo(() => {
    const decisions = dashboardQuery.data?.recent_decisions ?? [];
    return selectedSiteId
      ? decisions.filter((decision) => decision.site_id === selectedSiteId)
      : decisions;
  }, [dashboardQuery.data?.recent_decisions, selectedSiteId]);

  if (dashboardQuery.isLoading) {
    return <PageSkeleton />;
  }

  if (dashboardQuery.error) {
    return (
      <ErrorState
        description={errorMessage(dashboardQuery.error)}
        onRetry={() => void dashboardQuery.refetch()}
        title="The operational dashboard is unavailable"
      />
    );
  }

  const snapshot = dashboardQuery.data;
  if (!snapshot) {
    return null;
  }

  const selectedSite =
    snapshot.sites.find((site) => site.site_id === selectedSiteId) ?? null;
  const rosterError = presenceQuery.error ? errorMessage(presenceQuery.error) : null;
  const mutationError = exitMutation.error ? errorMessage(exitMutation.error) : null;

  return (
    <section aria-labelledby="operational-dashboard" className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Batch 5 · Operational overview</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950" id="operational-dashboard">
            Site access dashboard
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            Presence, occupancy, and gate activity are projections returned by the
            backend from immutable entry, exit, and decision records.
          </p>
        </div>
        <div className="w-full lg:w-72">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-600" htmlFor="dashboard-site">
            Operational site
          </label>
          <select
            className={fieldClass}
            id="dashboard-site"
            onChange={(event) => setSelectedSiteId(event.target.value)}
            value={selectedSiteId}
          >
            <option value="">All authorized sites</option>
            {snapshot.sites.map((site) => (
              <option key={site.site_id} value={site.site_id}>
                {site.site_name} · {site.country_code}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock3 aria-hidden="true" className="h-4 w-4" />
        Presence evaluated at effective demo time {formatDateTime(snapshot.as_of)} · simulated activity window begins{" "}
        {formatDateTime(snapshot.activity_window_started_at)} · live: refreshes every 15 seconds, last updated{" "}
        {dashboardQuery.dataUpdatedAt ? new Date(dashboardQuery.dataUpdatedAt).toLocaleTimeString(undefined, { timeZone: SITE_TIME_ZONE }) : "just now"}
      </p>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard icon={UsersRound} label="Currently present" value={selectedSite?.present_count ?? snapshot.totals.present_count} />
        <MetricCard icon={Activity} label="Active visits" tone="blue" value={selectedSite?.active_visit_count ?? snapshot.totals.active_visit_count} />
        <MetricCard icon={CheckCircle2} label="Access grants" value={selectedSite?.grant_count ?? snapshot.totals.grant_count} />
        <MetricCard icon={ShieldAlert} label="Access denials" tone="red" value={selectedSite?.denial_count ?? snapshot.totals.denial_count} />
        <MetricCard icon={Clock3} label="Overdue on site" tone="red" value={selectedSite?.overdue_count ?? snapshot.totals.overdue_count ?? 0} />
      </div>

      <PathBreakdown byPath={(selectedSite ?? snapshot.totals).by_path} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
        <section className="surface overflow-hidden" aria-labelledby="site-roster">
          <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <UsersRound aria-hidden="true" className="h-5 w-5 text-emerald-700" />
                <h3 className="text-base font-semibold text-slate-950" id="site-roster">
                  On-site roster
                </h3>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {selectedSite ? selectedSite.site_name : "All authorized sites"} · live safe presence projection
              </p>
            </div>
            {hasPermission("presence:write") ? (
              <StatusBadge tone="info">Exit recording enabled</StatusBadge>
            ) : null}
          </div>

          {hasPermission("presence:read") ? (
            rosterError ? (
              <ErrorState
                className="m-5"
                description={rosterError}
                onRetry={() => void presenceQuery.refetch()}
                title="The current roster could not be loaded"
              />
            ) : presenceQuery.isLoading ? (
              <div className="p-5"><PageSkeleton /></div>
            ) : (
              <RosterTable
                canRecordExit={hasPermission("presence:write")}
                isRecordingExit={exitMutation.isPending}
                onRecordExit={(person) => exitMutation.mutate(person)}
                people={presenceQuery.data ?? []}
              />
            )
          ) : (
            <EmptyState
              className="m-5"
              description="Your current role can see aggregate dashboard information but not the named current-presence roster."
              title="Roster permission is required"
            />
          )}

          {mutationError ? (
            <p aria-live="assertive" className="mx-5 mb-5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {mutationError}
            </p>
          ) : null}
          {exitConfirmation ? (
            <p
              aria-live="polite"
              className="mx-5 mb-5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
              role="status"
            >
              {exitConfirmation}
            </p>
          ) : null}
        </section>

        <section className="surface p-5" aria-labelledby="site-activity">
          <div className="flex items-center gap-2">
            <Building2 aria-hidden="true" className="h-5 w-5 text-emerald-700" />
            <h3 className="text-base font-semibold text-slate-950" id="site-activity">
              Site activity
            </h3>
          </div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Backend-returned operational counters for the activity window at effective demo time.
          </p>
          <div className="mt-5 space-y-3">
            {filteredSites.map((site) => <SiteMetrics key={site.site_id} site={site} />)}
          </div>
        </section>
      </div>

      <UploadedEvidence siteId={selectedSiteId} />

      <section className="surface overflow-hidden" aria-labelledby="recent-decisions">
        <div className="border-b border-slate-200 px-5 py-5">
          <div className="flex items-center gap-2">
            <MapPin aria-hidden="true" className="h-5 w-5 text-emerald-700" />
            <h3 className="text-base font-semibold text-slate-950" id="recent-decisions">
              Recent gate decisions
            </h3>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Decisions remain immutable; this view does not expose scanned token or identity-presentation data.
          </p>
        </div>

        {recentDecisions.length === 0 ? (
          <EmptyState
            className="m-5 border-dashed shadow-none"
            description="No gate decisions were returned for the selected site and activity window."
            title="No recent gate activity"
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {recentDecisions.map((decision) => (
              <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between" key={decision.gate_event_id}>
                <div>
                  <p className="font-semibold text-slate-950">
                    {decision.person_name ?? "Unresolved presentation"} · {decision.site_name ?? "Unknown site"}
                    {decision.source === "walk_up" ? " · walk-up" : ""}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {formatDateTime(decision.occurred_at)}
                    {decision.reason_codes.length > 0 ? ` · ${decision.reason_codes.join(", ")}` : ""}
                  </p>
                </div>
                <StatusBadge tone={decisionTone(decision.decision)}>{decision.decision}</StatusBadge>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          <ArrowUpFromLine aria-hidden="true" className="h-4 w-4 text-emerald-700" />
          {selectedSite?.entry_count ?? snapshot.totals.entry_count} recorded entries
        </span>
        <span className="inline-flex items-center gap-2">
          <ArrowDownToLine aria-hidden="true" className="h-4 w-4 text-slate-700" />
          {selectedSite?.exit_count ?? snapshot.totals.exit_count} recorded exits
        </span>
      </div>
    </section>
  );
}
