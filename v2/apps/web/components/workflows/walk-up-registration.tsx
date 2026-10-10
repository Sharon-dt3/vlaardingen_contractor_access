"use client";

import { type FormEvent, useEffect, useId, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api-client";

type SiteResponse = { site_key: string; site_name: string };

type RulesResponse = {
  id: string;
  version: number;
  language: string;
  available_languages: string[];
  title: string;
  intro: string;
  rules: { title: string; text: string }[];
  statement: string;
  is_sample: boolean;
};

type Receipt = {
  reference: string;
  site_name: string;
  registered_at: string;
  rules_version: number;
  language: string;
  pass_qr: string;
  pass_valid_until: string;
  emailed_to?: string | null;
};

type Pending = {
  verification_required: true;
  pending_id: string;
  email_hint: string;
  code_expires_at: string;
  resend_available_at: string;
};

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  nl: "Nederlands",
  fr: "Français",
  de: "Deutsch",
  pl: "Polski"
};

const POPULATIONS = [
  { value: "renewi_driver", label: "Renewi driver" },
  { value: "temporary_driver", label: "Temporary driver" },
  { value: "external_driver", label: "External driver" },
  { value: "maintenance_contractor", label: "Maintenance contractor" },
  { value: "permanent_contractor", label: "Permanent contractor" },
  { value: "visitor", label: "Visitor" }
];
const DEFAULT_POPULATION = "maintenance_contractor";

const FIELD = "mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-slate-950";

function messageFor(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "The request could not be completed.";
}

function initialLanguage(): string {
  if (typeof navigator === "undefined") return "en";
  return (navigator.language || "en").slice(0, 2).toLowerCase();
}

// PUBLIC_INTERFACE
/**
 * Arrival registration for someone who scanned the site's QR code and has no invitation.
 * One short form and the life-saving rules on one page. The API stores the registration
 * and the person's own confirmation together, or nothing at all.
 */
export function WalkUpRegistration({ siteKey }: { siteKey: string }) {
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [siteError, setSiteError] = useState("");
  const [language, setLanguage] = useState(initialLanguage);
  const [rules, setRules] = useState<RulesResponse | null>(null);
  const [rulesError, setRulesError] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [population, setPopulation] = useState(DEFAULT_POPULATION);
  const [website, setWebsite] = useState("");
  const [checked, setChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState("");
  const [notice, setNotice] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const checkboxId = useId();

  // Tick once a second only while a code is awaited, to count down the resend wait.
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [pending]);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<SiteResponse>(`/api/walk-up/sites/${encodeURIComponent(siteKey)}`, {
      signal: controller.signal,
      cache: "no-store"
    })
      .then(setSite)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setSiteError(messageFor(cause));
      });
    return () => controller.abort();
  }, [siteKey]);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<RulesResponse>(
      `/api/life-saving-rules/current?language=${encodeURIComponent(language)}`,
      { signal: controller.signal, cache: "no-store" }
    )
      .then((result) => {
        setRules(result);
        setRulesError("");
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setRulesError(messageFor(cause));
      });
    return () => controller.abort();
  }, [language]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!rules || !checked || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await apiRequest<Receipt | Pending>("/api/walk-up/registrations", {
        method: "POST",
        cache: "no-store",
        body: {
          site_key: siteKey,
          first_name: firstName,
          last_name: lastName,
          company_name: company,
          email,
          population,
          rules_version_id: rules.id,
          language: rules.language,
          confirmed: true,
          website
        }
      });
      if ("pending_id" in result) {
        setPending(result);
        setCode("");
        setCodeError("");
        setNotice("");
      } else {
        setReceipt(result);
      }
    } catch (cause) {
      setError(messageFor(cause));
      // The rules may have been updated while this page was open: show the new ones.
      if (cause instanceof ApiError && cause.status === 409) {
        setChecked(false);
        void apiRequest<RulesResponse>(
          `/api/life-saving-rules/current?language=${encodeURIComponent(language)}`,
          { cache: "no-store" }
        )
          .then(setRules)
          .catch(() => undefined);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pending || verifying || !/^\d{6}$/.test(code)) return;
    setVerifying(true);
    setCodeError("");
    setNotice("");
    try {
      const result = await apiRequest<Receipt>("/api/walk-up/registrations/verify", {
        method: "POST",
        cache: "no-store",
        body: { pending_id: pending.pending_id, code }
      });
      setReceipt(result);
      setPending(null);
    } catch (cause) {
      setCodeError(messageFor(cause));
      setCode("");
      // The registration is gone (expired, or too many wrong codes): go back to the form.
      if (cause instanceof ApiError && [404, 410, 429].includes(cause.status)) {
        setPending(null);
        setError(messageFor(cause));
      }
    } finally {
      setVerifying(false);
    }
  }

  async function resend() {
    if (!pending || verifying) return;
    setVerifying(true);
    setCodeError("");
    setNotice("");
    try {
      const result = await apiRequest<Pending>("/api/walk-up/registrations/resend", {
        method: "POST",
        cache: "no-store",
        body: { pending_id: pending.pending_id }
      });
      setPending(result);
      setNotice("A new code was sent. The earlier code no longer works.");
    } catch (cause) {
      setCodeError(messageFor(cause));
    } finally {
      setVerifying(false);
    }
  }

  if (siteError) {
    return (
      <div className="mx-auto max-w-xl py-8">
        <section className="surface p-6">
          <h1 className="text-xl font-bold text-slate-950">This QR code is not valid</h1>
          <p role="alert" className="mt-2 text-sm text-red-700">{siteError}</p>
          <p className="mt-2 text-sm text-slate-600">Ask site staff for help.</p>
        </section>
      </div>
    );
  }

  if (receipt) {
    return (
      <div className="mx-auto max-w-xl py-8">
        <section
          className="surface space-y-4 border-emerald-300 bg-emerald-50 p-6"
          role="status"
        >
          <p className="eyebrow">{receipt.site_name}</p>
          <h1 className="text-2xl font-bold text-emerald-900">You are registered</h1>
          <p className="text-sm text-emerald-900">
            Thank you, {firstName}. You confirmed that you have read and understood the
            life-saving rules (version {receipt.rules_version}). Your registration is recorded with
            the date and time.
          </p>
          <div className="rounded-xl border border-emerald-300 bg-white p-4 text-center">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Show this at the kiosk
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt="Your entry QR code. Show it to the gate kiosk."
              className="mx-auto mt-3 h-56 w-56 rounded-lg border bg-white p-2"
              src={receipt.pass_qr}
            />
            <a
              className="mt-3 inline-block rounded-lg border bg-white px-3 py-2 text-sm font-semibold text-slate-900"
              download={`entry-qr-${receipt.reference}.png`}
              href={receipt.pass_qr}
            >
              Download QR
            </a>
            <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              Or read out your reference
            </p>
            <p className="mt-1 font-mono text-3xl font-bold tracking-widest text-slate-950">
              {receipt.reference}
            </p>
            <p className="mt-2 text-xs text-slate-600">
              Registered {new Date(receipt.registered_at).toLocaleString()}. Valid until{" "}
              {new Date(receipt.pass_valid_until).toLocaleString()}.
            </p>
          </div>
          {receipt.emailed_to ? (
            <p className="text-sm text-emerald-900">
              A copy of this QR is being emailed to <strong>{receipt.emailed_to}</strong>. Check your spam
              folder if it does not arrive. You can show it from your email at the gate.
            </p>
          ) : null}
          <p className="text-sm text-emerald-900">
            Go to the gate kiosk and show this QR code, or give your reference. The gate operator
            will check your registration and let you in. Keep this screen open, and follow the
            rules at all times while you are on site.
          </p>
        </section>
      </div>
    );
  }

  if (pending) {
    const waitSeconds = Math.max(
      0,
      Math.ceil((new Date(pending.resend_available_at).getTime() - now) / 1000)
    );
    return (
      <div className="mx-auto max-w-xl py-8">
        <form className="surface space-y-5 p-6" onSubmit={(event) => void verify(event)}>
          <div>
            <p className="eyebrow">{site ? site.site_name : "Site registration"}</p>
            <h1 className="mt-2 text-2xl font-bold text-slate-950">Check your email</h1>
            <p className="mt-2 text-sm text-slate-700">
              We sent a 6-digit code to <strong>{pending.email_hint}</strong>. Enter it below to
              finish registering. It works for 10 minutes.
            </p>
          </div>
          <label className="block text-sm font-semibold text-slate-700">
            Code
            <input
              autoComplete="one-time-code"
              className={`${FIELD} text-center font-mono text-2xl tracking-[0.5em]`}
              inputMode="numeric"
              maxLength={6}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              pattern="\d{6}"
              value={code}
            />
          </label>
          {codeError ? (
            <p role="alert" className="text-sm text-red-700">
              {codeError}
            </p>
          ) : null}
          {notice ? (
            <p role="status" className="text-sm text-emerald-800">
              {notice}
            </p>
          ) : null}
          <button
            className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
            disabled={verifying || code.length !== 6}
            type="submit"
          >
            {verifying ? "Checking…" : "Verify and register"}
          </button>
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <button
              className="font-semibold text-emerald-800 underline disabled:text-slate-400 disabled:no-underline"
              disabled={verifying || waitSeconds > 0}
              onClick={() => void resend()}
              type="button"
            >
              {waitSeconds > 0 ? `Send a new code in ${waitSeconds}s` : "Send a new code"}
            </button>
            <button
              className="text-slate-700 underline"
              onClick={() => {
                setPending(null);
                setCode("");
                setCodeError("");
                setNotice("");
                setChecked(false);
              }}
              type="button"
            >
              Use a different email
            </button>
          </div>
          <p className="text-xs text-slate-600">
            Nothing is saved until you enter the code. Check your spam folder if it does not
            arrive.
          </p>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-6 py-4 sm:py-8">
      <header>
        <p className="eyebrow">{site ? site.site_name : "Site registration"}</p>
        <h1 className="mt-2 text-2xl font-bold text-slate-950">Register before you enter</h1>
        <p className="mt-2 text-sm text-slate-600">
          Tell us who you are, read the life-saving rules, and confirm that you understood them.
          It takes about a minute. No invitation is needed.
        </p>
      </header>

      <form className="surface space-y-6 p-5 sm:p-6" onSubmit={(event) => void submit(event)}>
        <fieldset className="space-y-4">
          <legend className="text-base font-semibold text-slate-950">Your details</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-semibold text-slate-700">
              First name
              <input
                autoComplete="given-name"
                className={FIELD}
                maxLength={100}
                onChange={(event) => setFirstName(event.target.value)}
                required
                value={firstName}
              />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Last name
              <input
                autoComplete="family-name"
                className={FIELD}
                maxLength={120}
                onChange={(event) => setLastName(event.target.value)}
                required
                value={lastName}
              />
            </label>
          </div>
          <label className="block text-sm font-semibold text-slate-700">
            Company
            <input
              autoComplete="organization"
              className={FIELD}
              maxLength={180}
              minLength={2}
              onChange={(event) => setCompany(event.target.value)}
              required
              value={company}
            />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            Email
            <input
              autoComplete="email"
              className={FIELD}
              inputMode="email"
              maxLength={254}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            I am a
            <select
              className={FIELD}
              onChange={(event) => setPopulation(event.target.value)}
              value={population}
            >
              {POPULATIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {/* Real people never see or fill this; automated form fillers often do. */}
          <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
            <label>
              Website
              <input
                autoComplete="off"
                onChange={(event) => setWebsite(event.target.value)}
                tabIndex={-1}
                value={website}
              />
            </label>
          </div>
        </fieldset>

        <section aria-labelledby="walk-up-rules-heading" className="space-y-4">
          {!rules && !rulesError ? (
            <p className="text-sm text-slate-600">Loading the life-saving rules…</p>
          ) : null}
          {rulesError ? (
            <p role="alert" className="text-sm text-red-700">{rulesError}</p>
          ) : null}
          {rules ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-950" id="walk-up-rules-heading">
                  {rules.title}
                </h2>
                {rules.available_languages.length > 1 ? (
                  <label className="text-xs font-semibold text-slate-700">
                    Language
                    <select
                      className="mt-1 block rounded-lg border bg-white px-2 py-1.5 text-sm text-slate-950"
                      onChange={(event) => {
                        setChecked(false);
                        setLanguage(event.target.value);
                      }}
                      value={rules.language}
                    >
                      {rules.available_languages.map((code) => (
                        <option key={code} value={code}>
                          {LANGUAGE_NAMES[code] ?? code}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>

              {rules.is_sample ? (
                <p
                  className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                  role="note"
                >
                  Sample wording for the demonstration. Renewi&apos;s own life-saving rules and
                  legal text replace this before real use.
                </p>
              ) : null}

              <p className="text-sm text-slate-700">{rules.intro}</p>
              <ol className="space-y-3">
                {rules.rules.map((rule, index) => (
                  <li className="flex gap-3" key={rule.title}>
                    <span
                      aria-hidden="true"
                      className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-700 text-xs font-bold text-white"
                    >
                      {index + 1}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-slate-950">{rule.title}</p>
                      <p className="text-sm text-slate-700">{rule.text}</p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="rounded-xl border border-slate-300 bg-slate-50 p-4">
                <div className="flex items-start gap-3">
                  <input
                    checked={checked}
                    className="mt-1 h-5 w-5 shrink-0 accent-emerald-700"
                    id={checkboxId}
                    onChange={(event) => setChecked(event.target.checked)}
                    type="checkbox"
                  />
                  <label className="text-sm font-semibold text-slate-900" htmlFor={checkboxId}>
                    {rules.statement}
                  </label>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {error ? (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        ) : null}

        <button
          className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
          disabled={!rules || !checked || submitting}
          type="submit"
        >
          {submitting ? "Registering…" : "Register and confirm"}
        </button>
        <p className="text-xs text-slate-600">
          Your name, company and email are stored with the date, time and the version of the rules
          you read, so the site can see that you confirmed before you entered. No identity document
          is needed.
        </p>
      </form>
    </div>
  );
}
