"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api-client";

type Info = { display_name: string; email: string; role_label: string };

const FIELD =
  "mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950";

// The same checks the server makes, shown as the person types.
export function passwordRules(password: string, email: string) {
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { ok: password.length >= 12, text: "At least 12 characters" },
    { ok: /[A-Za-z]/.test(password) && /[^A-Za-z]/.test(password), text: "Letters mixed with numbers or symbols" },
    { ok: !(local.length >= 4 && password.toLowerCase().includes(local)), text: "Does not contain your email name" }
  ];
}

// PUBLIC_INTERFACE
/**
 * The page behind an emailed one-time link: shows who it is for, then lets them choose a password.
 * Used for the first password (invitation) and for a reset.
 */
export function PasswordLinkForm({
  lookupPath,
  submitPath,
  heading,
  intro,
  doneHeading,
  doneText,
  badLinkText
}: {
  lookupPath: string;
  submitPath: string;
  heading: string;
  intro: (info: Info) => string;
  doneHeading: string;
  doneText: string;
  badLinkText: string;
}) {
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<Info | null>(null);
  const [problem, setProblem] = useState("");
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const secret = new URLSearchParams(window.location.search).get("token") ?? "";
    // Keep the link's secret out of the address bar and browser history from here on.
    window.history.replaceState(null, "", window.location.pathname);
    if (!secret) {
      setProblem("This link is not complete. Open it again from your email.");
      setChecking(false);
      return;
    }
    setToken(secret);
    apiRequest<Info>(lookupPath, { method: "POST", body: { token: secret } })
      .then(setInfo)
      .catch((cause) =>
        setProblem(
          cause instanceof ApiError && cause.status === 429
            ? "Too many attempts. Try again in a few minutes."
            : badLinkText
        )
      )
      .finally(() => setChecking(false));
  }, [lookupPath, badLinkText]);

  const checks = passwordRules(password, info?.email ?? "");
  const ready = checks.every((check) => check.ok) && password === again && password.length > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(submitPath, { method: "POST", body: { token, password } });
      setDone(true);
      setPassword("");
      setAgain("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Your password could not be saved. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4 py-10">
      <p className="eyebrow">Renewi Access</p>
      {checking ? <p className="mt-4 text-sm text-slate-600">Checking your link…</p> : null}
      {!checking && problem ? (
        <div className="mt-4 space-y-4">
          <h1 className="text-2xl font-semibold text-slate-950">This link cannot be used</h1>
          <p className="text-sm text-slate-700" role="alert">{problem}</p>
          <Link className="text-sm font-semibold text-emerald-800 underline" href="/login">Go to sign in</Link>
        </div>
      ) : null}
      {!checking && info && !done ? (
        <form className="surface mt-2 space-y-5 p-5 sm:p-6" onSubmit={(event) => void submit(event)}>
          <div>
            <h1 className="text-2xl font-semibold text-slate-950">{heading}</h1>
            <p className="mt-1 text-sm text-slate-600">{intro(info)}</p>
          </div>
          <label className="block text-sm font-semibold text-slate-700">
            New password
            <input
              autoComplete="new-password"
              className={FIELD}
              maxLength={128}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <ul className="space-y-1 text-xs">
            {checks.map((check) => (
              <li className={check.ok ? "text-emerald-800" : "text-slate-500"} key={check.text}>
                {check.ok ? "✓" : "○"} {check.text}
              </li>
            ))}
          </ul>
          <label className="block text-sm font-semibold text-slate-700">
            Type it again
            <input
              autoComplete="new-password"
              className={FIELD}
              maxLength={128}
              onChange={(event) => setAgain(event.target.value)}
              required
              type="password"
              value={again}
            />
          </label>
          {again && password !== again ? <p className="text-xs text-red-700">The two passwords do not match.</p> : null}
          {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
          <button
            className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
            disabled={!ready || busy}
            type="submit"
          >
            {busy ? "Saving" : "Save password"}
          </button>
        </form>
      ) : null}
      {done ? (
        <div className="surface mt-2 space-y-3 p-5 sm:p-6">
          <h1 className="text-2xl font-semibold text-slate-950">{doneHeading}</h1>
          <p className="text-sm text-slate-700">{doneText}</p>
          <Link className="inline-block rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white" href="/login">
            Go to sign in
          </Link>
        </div>
      ) : null}
    </main>
  );
}
