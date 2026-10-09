"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiRequest, getApiBaseUrl } from "@/lib/api-client";
import { formatDateTime } from "@/lib/domain";
import { LifeSavingRulesConfirmation } from "@/components/workflows/life-saving-rules-confirmation";

type RegistrationStatus = {
  company_name: string;
  population: string;
  registration_completed: boolean;
  evidence_uploaded: boolean;
  life_saving_rules_confirmed?: boolean;
  life_saving_rules_confirmed_at?: string | null;
};

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const DRIVER_POPULATIONS = new Set([
  "renewi_driver",
  "temporary_driver",
  "external_driver"
]);

function messageFor(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "The request could not be completed.";
}

// PUBLIC_INTERFACE
/**
 * Provides a recipient-only registration form after email acceptance.
 * The API, not this component, authorizes the capability and enforces
 * required evidence and the administrator verification boundary.
 */
export function InviteeRegistration() {
  const [token, setToken] = useState("");
  // The link is read once and then removed from the address bar. React's development
  // mode runs effects twice, so the first reading must be remembered for the second.
  const linkSecret = useRef<string | null>(null);
  const [status, setStatus] = useState<RegistrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [expiryDate, setExpiryDate] = useState("");

  useEffect(() => {
    if (linkSecret.current === null) {
      linkSecret.current = new URLSearchParams(window.location.search).get("token") ?? "";
    }
    const secret = linkSecret.current;
    // Avoid copying the capability into subsequent navigation and history entries.
    window.history.replaceState(null, "", "/register");
    if (!secret) {
      setError("This registration link is missing or invalid.");
      setLoading(false);
      return;
    }
    setToken(secret);
    const controller = new AbortController();
    apiRequest<RegistrationStatus>(
      `/api/invitations/registration?token=${encodeURIComponent(secret)}`,
      { signal: controller.signal, cache: "no-store" }
    )
      .then((result) => setStatus(result))
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(messageFor(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!status || !token || !file || submitting) return;
    // The API validates the date again and keeps the submitted evidence unverified.
    if (!expiryDate) {
      setError("Enter the expiry date shown on your identity document.");
      return;
    }
    if (file.size === 0 || file.size > MAX_UPLOAD_BYTES) {
      setError("Choose a document between 1 byte and 5 MiB.");
      return;
    }
    setSubmitting(true);
    setError("");
    const form = new FormData();
    form.set("token", token);
    form.set("first_name", firstName.trim());
    form.set("last_name", lastName.trim());
    form.set("expiry_date", expiryDate);
    form.set(
      "evidence_type",
      DRIVER_POPULATIONS.has(status.population) ? "driving_licence" : "id_card"
    );
    form.set("file", file);
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/invitations/registration`, {
        method: "POST",
        body: form,
        credentials: "include",
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      const result = await response.json();
      if (!response.ok) {
        throw new ApiError(
          typeof result.detail === "string" ? result.detail : "Registration failed.",
          response.status
        );
      }
      setStatus(result as RegistrationStatus);
      setFile(null);
      // The link stays in memory (never in the address bar) until the rules are confirmed.
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6 py-8">
      <div>
        <p className="eyebrow">Accepted invitation</p>
        <h1 className="mt-2 text-2xl font-bold text-slate-950">
          Complete your registration
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Your details and identity document will be reviewed by an administrator.
          Submitting this form does not approve training or grant site access. You
          must also confirm that you have read and understood the life-saving rules
          before you can be let in.
        </p>
      </div>
      <section className="surface p-6" aria-live="polite">
        {loading ? (
          <p className="text-sm text-slate-600">Checking your invitation…</p>
        ) : error && !status ? (
          <p role="alert" className="text-sm text-red-700">{error}</p>
        ) : status?.registration_completed ? (
          <div className="space-y-6">
            <div>
              <h2 className="font-semibold text-emerald-800">Registration submitted</h2>
              <p className="mt-2 text-sm text-slate-700">
                Your document, name and stated ID expiry date were sent for administrator verification.
                Training, approval and access remain unavailable until that review is complete.
              </p>
            </div>
            {status.life_saving_rules_confirmed ? (
              <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4" role="status">
                <h2 className="font-semibold text-emerald-900">Life-saving rules confirmed</h2>
                <p className="mt-1 text-sm text-emerald-900">
                  You confirmed that you read and understood the life-saving rules
                  {status.life_saving_rules_confirmed_at
                    ? ` on ${formatDateTime(status.life_saving_rules_confirmed_at)}`
                    : ""}
                  . The site can see this when you arrive.
                </p>
              </div>
            ) : token ? (
              <LifeSavingRulesConfirmation
                onConfirmed={(confirmation) => {
                  setStatus((current) =>
                    current
                      ? {
                          ...current,
                          life_saving_rules_confirmed: true,
                          life_saving_rules_confirmed_at: confirmation.acknowledged_at
                        }
                      : current
                  );
                  setToken("");
                }}
                token={token}
              />
            ) : null}
          </div>
        ) : status ? (
          <form className="space-y-5" onSubmit={(event) => void submit(event)}>
            <p className="text-sm text-slate-700">
              Invitation for <strong>{status.company_name}</strong>. Your invited
              email and company are fixed by the invitation.
            </p>
            <label className="block text-sm font-semibold text-slate-700">
              First name as shown on your document
              <input
                autoComplete="given-name"
                className="mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-slate-950"
                maxLength={100}
                onChange={(event) => setFirstName(event.target.value)}
                required
                value={firstName}
              />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Last name as shown on your document
              <input
                autoComplete="family-name"
                className="mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-slate-950"
                maxLength={120}
                onChange={(event) => setLastName(event.target.value)}
                required
                value={lastName}
              />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              {DRIVER_POPULATIONS.has(status.population)
                ? "Driving licence"
                : "ID card"}
              <input
                accept=".pdf,.png,.jpg,.jpeg,.txt,.json"
                className="mt-2 block w-full text-sm"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setError("");
                }}
                required
                type="file"
              />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              ID expiry date as shown on your document
              <input
                className="mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-slate-950"
                onChange={(event) => setExpiryDate(event.target.value)}
                required
                type="date"
                value={expiryDate}
              />
              <span className="mt-1 block text-xs font-normal text-slate-600">
                This date is self-reported and will be checked against your document.
              </span>
            </label>
            <p className="text-xs text-slate-600">
              Maximum 5 MiB. For the local demo, documents must be visibly marked
              DEMO or NOT A REAL CREDENTIAL unless real-document processing is configured.
            </p>
            {error ? <p role="alert" className="text-sm text-red-700">{error}</p> : null}
            <button
              className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              disabled={submitting || !file || !firstName.trim() || !lastName.trim() || !expiryDate}
              type="submit"
            >
              {submitting ? "Submitting…" : "Submit registration for review"}
            </button>
          </form>
        ) : null}
      </section>
    </div>
  );
}
