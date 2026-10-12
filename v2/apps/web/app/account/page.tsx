"use client";

import { type FormEvent, useState } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { passwordRules } from "@/components/users/password-link-form";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, apiRequest } from "@/lib/api-client";

const FIELD =
  "mt-1 block w-full max-w-md rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950";

// PUBLIC_INTERFACE
/**
 * Lets a signed-in person change their own password. Other browsers are signed out.
 */
export default function AccountPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const checks = passwordRules(next, user?.handle.includes("@") ? user.handle : "");
  const ready = current.length > 0 && checks.every((check) => check.ok) && next === again;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    setDone(false);
    try {
      await apiRequest("/auth/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next }
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setAgain("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Your password could not be changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-7">
      <PageHeader
        description="Change the password you sign in with. Any other browser where you are signed in will be signed out."
        eyebrow="Your account"
        title="Change password"
      />
      <form className="surface space-y-5 p-5 sm:p-6" onSubmit={(event) => void submit(event)}>
        <label className="block text-sm font-semibold text-slate-700">
          Current password
          <input autoComplete="current-password" className={FIELD} maxLength={256} onChange={(e) => setCurrent(e.target.value)} required type="password" value={current} />
        </label>
        <label className="block text-sm font-semibold text-slate-700">
          New password
          <input autoComplete="new-password" className={FIELD} maxLength={128} onChange={(e) => setNext(e.target.value)} required type="password" value={next} />
        </label>
        <ul className="space-y-1 text-xs">
          {checks.map((check) => (
            <li className={check.ok ? "text-emerald-800" : "text-slate-500"} key={check.text}>
              {check.ok ? "✓" : "○"} {check.text}
            </li>
          ))}
        </ul>
        <label className="block text-sm font-semibold text-slate-700">
          Type the new password again
          <input autoComplete="new-password" className={FIELD} maxLength={128} onChange={(e) => setAgain(e.target.value)} required type="password" value={again} />
        </label>
        {again && next !== again ? <p className="text-xs text-red-700">The two passwords do not match.</p> : null}
        {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
        {done ? (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
            Your password was changed. We emailed you a notice.
          </p>
        ) : null}
        <button
          className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          disabled={!ready || busy}
          type="submit"
        >
          {busy ? "Saving" : "Change password"}
        </button>
      </form>
    </div>
  );
}
