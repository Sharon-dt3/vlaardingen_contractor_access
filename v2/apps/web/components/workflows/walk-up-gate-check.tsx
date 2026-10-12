"use client";

import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { StatusBadge } from "@/components/ui/status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import { enumLabel, formatDateTime, formatInSiteZone } from "@/lib/domain";
import { GateQrScanner } from "@/components/workflows/gate-qr-scanner";
import { WalkUpCameraScanner } from "@/components/workflows/walk-up-camera-scanner";

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

type SiteLink = { site_key: string; site_name: string };

type Arrival = {
  registration_id: string;
  reference: string;
  first_name: string;
  last_name: string;
  company_name: string;
  population: string;
  site_name: string;
  registered_at: string;
  pass_valid_from: string;
  pass_valid_until: string;
  site_timezone: string;
  rules_version: number | null;
  rules_language: string | null;
  eligible: boolean;
  reasons: { code: string; message: string }[];
  admitted_at: string | null;
  admitted_by: string | null;
  email_verified: boolean;
  exited_at: string | null;
  refusal_count: number;
  last_refused_at: string | null;
};

const REFUSAL_REASONS = [
  { value: "identity_mismatch", label: "The person does not match their ID" },
  { value: "not_expected", label: "Nobody could confirm they are expected" },
  { value: "other", label: "Another reason (write a note)" }
];

const PASS_PREFIX = "renewi-walkup:";

// Current entry QR codes read "renewi-walkup:<reference>:<secret>". The reference is not secret,
// so it can go straight into the box; the secret is kept aside and sent when the officer checks.
function parsePass(payload: string): { reference: string; secret: string } | null {
  const text = payload.trim();
  if (!text.toLowerCase().startsWith(PASS_PREFIX)) return null;
  const parts = text.slice(PASS_PREFIX.length).split(":");
  if (parts.length === 2 && /^[0-9A-Fa-f]{8}$/.test(parts[0]) && parts[1]) {
    return { reference: parts[0].toUpperCase(), secret: parts[1] };
  }
  return null;
}

function messageFor(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "The request could not be completed.";
}

// PUBLIC_INTERFACE
/**
 * Kiosk check for people who registered through the entrance QR code: scan the QR on their
 * phone, or type the reference they read out, see who they are and whether they confirmed
 * the life-saving rules, then let them in. The server decides; this screen only shows it.
 */
export function WalkUpGateCheck() {
  const sites = useQuery({
    queryKey: ["walk-up", "gate-sites"],
    queryFn: () => apiRequest<SiteLink[]>("/api/walk-up/sites")
  });
  const [code, setCode] = useState("");
  const [scanned, setScanned] = useState<{ reference: string; secret: string } | null>(null);
  const [arrival, setArrival] = useState<Arrival | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusing, setRefusing] = useState(false);
  const [refuseReason, setRefuseReason] = useState(REFUSAL_REASONS[0].value);
  const [refuseNote, setRefuseNote] = useState("");
  const [notice, setNotice] = useState("");

  const site = sites.data?.[0];

  async function lookup(value: string) {
    if (!site || !value.trim() || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setArrival(null);
    try {
      setArrival(
        await apiRequest<Arrival>("/api/walk-up/gate/lookup", {
          method: "POST",
          cache: "no-store",
          body: { site_key: site.site_key, code: value.trim() }
        })
      );
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }

  async function admit() {
    if (!site || !arrival || busy) return;
    setBusy(true);
    setError("");
    try {
      setArrival(
        await apiRequest<Arrival>("/api/walk-up/gate/admit", {
          method: "POST",
          cache: "no-store",
          body: { site_key: site.site_key, registration_id: arrival.registration_id }
        })
      );
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }

  async function recordExit() {
    if (!site || !arrival || busy) return;
    setBusy(true);
    setError("");
    try {
      setArrival(
        await apiRequest<Arrival>("/api/walk-up/gate/exit", {
          method: "POST",
          cache: "no-store",
          body: { site_key: site.site_key, registration_id: arrival.registration_id }
        })
      );
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }

  async function refuse() {
    if (!site || !arrival || busy) return;
    if (refuseReason === "other" && !refuseNote.trim()) {
      setError("Write a short note when the reason is other.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setArrival(
        await apiRequest<Arrival>("/api/walk-up/gate/refuse", {
          method: "POST",
          cache: "no-store",
          body: {
            site_key: site.site_key,
            registration_id: arrival.registration_id,
            reason: refuseReason,
            note: refuseNote.trim()
          }
        })
      );
      setRefusing(false);
      setRefuseNote("");
      setNotice("The refusal was recorded in the audit trail.");
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setArrival(null);
    setError("");
    setCode("");
    setScanned(null);
    setRefusing(false);
    setRefuseNote("");
    setNotice("");
  }

  function handleScan(payload: string) {
    setArrival(null);
    setError("");
    const pass = parsePass(payload);
    if (pass) {
      // Show the reference and wait: the officer presses Check.
      setScanned(pass);
      setCode(pass.reference);
      return;
    }
    // An earlier QR code without a reference: nothing to show first, so check it straight away.
    setScanned(null);
    setCode(payload);
    void lookup(payload);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // If the box still holds the reference that was scanned, send the scanned secret too.
    const sameAsScan = scanned && code.trim().toUpperCase() === scanned.reference;
    void lookup(sameAsScan ? `${PASS_PREFIX}${scanned.reference}:${scanned.secret}` : code);
  }

  if (!site) return null;

  return (
    <section aria-labelledby="walk-up-gate-heading" className="surface space-y-5 p-5 sm:p-6">
      <div>
        <p className="eyebrow">Walk-up arrivals · {site.site_name}</p>
        <h2 className="mt-1 text-xl font-semibold text-slate-950" id="walk-up-gate-heading">
          Check someone who registered at the entrance
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Scan the QR code on their phone, or type the reference they read out. You will see who
          they are and whether they confirmed the life-saving rules before you let them in.
        </p>
      </div>

      {!arrival ? (
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-4">
            <WalkUpCameraScanner disabled={busy} onScan={handleScan} />
            <GateQrScanner
              disabled={busy}
              idSuffix="-walk-up"
              onError={setError}
              onScan={handleScan}
            />
          </div>
          <form className="space-y-3" onSubmit={submit}>
            <label className="block text-sm font-semibold text-slate-700">
              Reference (filled in by a scan, or type it)
              <input
                autoCapitalize="characters"
                autoComplete="off"
                className="mt-1 block w-full rounded-lg border bg-white px-3 py-2 font-mono text-lg uppercase tracking-widest text-slate-950"
                maxLength={200}
                onChange={(event) => setCode(event.target.value)}
                placeholder="B0412408"
                value={code}
              />
            </label>
            <button
              className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              disabled={busy || !code.trim()}
              type="submit"
            >
              {busy ? "Checking…" : "Check"}
            </button>
          </form>
        </div>
      ) : (
        <div
          className={`space-y-4 rounded-xl border p-5 ${
            arrival.exited_at
              ? "border-slate-300 bg-slate-100"
              : arrival.admitted_at
              ? "border-emerald-300 bg-emerald-50"
              : arrival.eligible
                ? "border-slate-300 bg-slate-50"
                : "border-red-300 bg-red-50"
          }`}
          role="status"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-2xl font-bold text-slate-950">
                {arrival.first_name} {arrival.last_name}
              </p>
              <p className="text-sm text-slate-700">
                {arrival.company_name} · {enumLabel(arrival.population)}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Reference <span className="font-mono">{arrival.reference}</span> · registered{" "}
                {formatDateTime(arrival.registered_at)}
              </p>
            </div>
            {arrival.exited_at ? (
              <StatusBadge tone="neutral">Left</StatusBadge>
            ) : arrival.admitted_at ? (
              <StatusBadge tone="success">On site</StatusBadge>
            ) : arrival.eligible ? (
              <StatusBadge tone="success">May enter</StatusBadge>
            ) : (
              <StatusBadge tone="danger">Do not admit</StatusBadge>
            )}
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-slate-900">
            <dt className="font-semibold">Entry from</dt>
            <dd>{formatInSiteZone(arrival.pass_valid_from, arrival.site_timezone)}</dd>
            <dt className="font-semibold">Exit by</dt>
            <dd>
              {formatInSiteZone(arrival.pass_valid_until, arrival.site_timezone)} ·{" "}
              <strong>{qrTimeLeft(arrival.pass_valid_from, arrival.pass_valid_until)}</strong>
            </dd>
          </dl>

          <p className="text-sm font-semibold text-slate-900">
            {arrival.reasons.some((reason) => reason.code.startsWith("LIFE_SAVING"))
              ? "Life-saving rules: NOT confirmed for the current version"
              : `Life-saving rules: confirmed (version ${arrival.rules_version}, ${(
                  arrival.rules_language ?? ""
                ).toUpperCase()})`}
          </p>

          <p className={`text-sm font-semibold ${arrival.email_verified ? "text-slate-900" : "text-amber-800"}`}>
            {arrival.email_verified
              ? "Email: verified with a code"
              : "Email: not verified (registered without the email check)"}
          </p>

          {arrival.reasons.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-red-800">
              {arrival.reasons.map((reason) => (
                <li key={reason.code}>{reason.message}</li>
              ))}
            </ul>
          ) : null}

          {!arrival.eligible && !arrival.admitted_at && !arrival.exited_at ? (
            <p className="text-xs text-slate-700">This refusal has been recorded in the audit trail.</p>
          ) : null}
          {arrival.refusal_count > 0 ? (
            <p className="text-xs font-semibold text-red-800">
              Refused {arrival.refusal_count} time{arrival.refusal_count === 1 ? "" : "s"} on record
              {arrival.last_refused_at ? `, last at ${formatDateTime(arrival.last_refused_at)}` : ""}.
            </p>
          ) : null}
          {notice ? (
            <p className="text-sm font-semibold text-slate-900" role="status">
              {notice}
            </p>
          ) : null}

          {arrival.admitted_at ? (
            <p className="text-sm text-emerald-900">
              Let in at {formatDateTime(arrival.admitted_at)}
              {arrival.admitted_by ? ` by ${arrival.admitted_by}` : ""}.
              {arrival.exited_at ? ` Left at ${formatDateTime(arrival.exited_at)}.` : " Still on site."}
            </p>
          ) : null}

          {refusing ? (
            <div className="space-y-3 rounded-lg border border-red-300 bg-white p-4">
              <p className="text-sm font-semibold text-slate-900">Why is this person being turned away?</p>
              <select
                className="block w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-950"
                onChange={(event) => setRefuseReason(event.target.value)}
                value={refuseReason}
              >
                {REFUSAL_REASONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              <input
                className="block w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-950"
                maxLength={200}
                onChange={(event) => setRefuseNote(event.target.value)}
                placeholder={refuseReason === "other" ? "Note (required)" : "Note (optional)"}
                value={refuseNote}
              />
              <div className="flex flex-wrap gap-3">
                <button
                  className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                  disabled={busy}
                  onClick={() => void refuse()}
                  type="button"
                >
                  {busy ? "Recording…" : "Record refusal"}
                </button>
                <button
                  className="rounded-lg border px-4 py-2 text-sm font-semibold text-slate-800"
                  onClick={() => setRefusing(false)}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap gap-3">
            {!arrival.admitted_at && !arrival.exited_at && !refusing ? (
              <button
                className="rounded-lg border border-red-300 px-4 py-2.5 text-sm font-semibold text-red-800"
                onClick={() => {
                  setNotice("");
                  setRefusing(true);
                }}
                type="button"
              >
                Refuse entry
              </button>
            ) : null}
            {arrival.eligible && !arrival.admitted_at ? (
              <button
                className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                disabled={busy}
                onClick={() => void admit()}
                type="button"
              >
                {busy ? "Recording…" : "Let in"}
              </button>
            ) : null}
            {arrival.admitted_at && !arrival.exited_at ? (
              <button
                className="rounded-lg bg-slate-800 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                disabled={busy}
                onClick={() => void recordExit()}
                type="button"
              >
                {busy ? "Recording…" : "Record exit"}
              </button>
            ) : null}
            <button
              className="rounded-lg border px-4 py-2.5 text-sm font-semibold text-slate-800"
              onClick={reset}
              type="button"
            >
              Next person
            </button>
          </div>
        </div>
      )}

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
