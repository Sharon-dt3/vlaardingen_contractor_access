"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api-client";

// PUBLIC_INTERFACE
/**
 * Asks for the email, then always shows the same answer so nobody can find out who has an account.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest("/auth/forgot-password", { method: "POST", body: { email } });
      setSent(true);
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 429
          ? "Too many attempts. Try again in a few minutes."
          : "Enter a valid email address."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4 py-10">
      <p className="eyebrow">Renewi Access</p>
      <h1 className="mt-2 text-2xl font-semibold text-slate-950">Forgot your password?</h1>
      {sent ? (
        <div className="surface mt-5 space-y-3 p-5" role="status">
          <p className="text-sm text-slate-800">
            If that email belongs to an account, we have sent a link to reset the password. It works once and
            expires in 1 hour. Check your spam folder if it does not arrive.
          </p>
          <Link className="text-sm font-semibold text-emerald-800 underline" href="/login">Back to sign in</Link>
        </div>
      ) : (
        <form className="surface mt-5 space-y-4 p-5" onSubmit={(event) => void submit(event)}>
          <p className="text-sm text-slate-600">Enter the email you sign in with and we will send you a link.</p>
          <label className="block text-sm font-semibold text-slate-700">
            Email
            <input
              autoComplete="email"
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950"
              maxLength={254}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
          <button
            className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
            disabled={busy}
            type="submit"
          >
            {busy ? "Sending" : "Send reset link"}
          </button>
          <Link className="block text-center text-sm font-semibold text-emerald-800 underline" href="/login">Back to sign in</Link>
        </form>
      )}
    </main>
  );
}
