"use client";

import { useEffect, useId, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api-client";

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

type ConfirmationResponse = {
  rules_version: number;
  language: string;
  acknowledged_at: string;
};

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  nl: "Nederlands",
  fr: "Français",
  de: "Deutsch",
  pl: "Polski"
};

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
 * Shows the life-saving rules and records the contractor's own confirmation that
 * they have read and understood them. Only the holder of the registration link can
 * confirm. Staff cannot confirm on someone's behalf, and the API alone decides
 * whether the confirmation is accepted.
 */
export function LifeSavingRulesConfirmation({
  token,
  onConfirmed
}: {
  token: string;
  onConfirmed: (confirmation: ConfirmationResponse) => void;
}) {
  const [language, setLanguage] = useState(initialLanguage);
  const [rules, setRules] = useState<RulesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [checked, setChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const checkboxId = useId();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    apiRequest<RulesResponse>(
      `/api/life-saving-rules/current?language=${encodeURIComponent(language)}`,
      { signal: controller.signal, cache: "no-store" }
    )
      .then((result) => {
        setRules(result);
        setError("");
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(messageFor(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [language]);

  async function confirm() {
    if (!rules || !checked || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await apiRequest<ConfirmationResponse>(
        "/api/invitations/registration/life-saving-confirmation",
        {
          method: "POST",
          cache: "no-store",
          body: {
            token,
            rules_version_id: rules.id,
            language: rules.language,
            confirmed: true
          }
        }
      );
      onConfirmed(result);
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

  if (loading && !rules) {
    return <p className="text-sm text-slate-600">Loading the life-saving rules…</p>;
  }
  if (!rules) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {error || "The life-saving rules are not available right now."}
      </p>
    );
  }

  return (
    <section aria-labelledby="life-saving-heading" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Step 2 of 2</p>
          <h2 className="mt-1 text-lg font-bold text-slate-950" id="life-saving-heading">
            {rules.title}
          </h2>
        </div>
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
          Sample wording for the demonstration. Renewi&apos;s own life-saving rules and legal text
          replace this before real use.
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

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <button
        className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        disabled={!checked || submitting}
        onClick={() => void confirm()}
        type="button"
      >
        {submitting ? "Confirming…" : "Confirm I have read and understood"}
      </button>
      <p className="text-xs text-slate-600">
        Your confirmation is recorded with the date and time and the version of the rules you read.
        The site can see that you confirmed before you are allowed in.
      </p>
    </section>
  );
}
