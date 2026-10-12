"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, ShieldCheck, UserRoundCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useAuth } from "@/components/auth/auth-provider";
import { StatusBadge } from "@/components/ui/status-badge";
import { ApiError } from "@/lib/api-client";

const loginSchema = z.object({
  handle: z.string().min(3, "Enter your email address."),
  password: z.string().min(1, "Enter your password.")
});

type LoginValues = z.infer<typeof loginSchema>;

const accounts = [
  ["admin.demo", "System Admin"]
] as const;

// PUBLIC_INTERFACE
/**
 * Authenticates the administrator account for the local demo.
 */
export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading, login } = useAuth();
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      handle: "admin.demo",
      password: "renewi-demo-access"
    }
  });
  const selectedHandle = form.watch("handle");

  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/");
    }
  }, [isLoading, router, user]);

  async function onSubmit(values: LoginValues) {
    try {
      await login(values);
      const nextPath = searchParams.get("next");
      router.replace(nextPath?.startsWith("/") ? nextPath : "/");
    } catch (error) {
      form.setError("root", {
        message:
          error instanceof ApiError
            ? error.message
            : "Sign-in could not be completed. Try again."
      });
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(34rem,1.1fr)]">
      <section className="relative hidden overflow-hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col">
        <div className="absolute -right-32 top-16 h-96 w-96 rounded-full bg-emerald-400/15 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-emerald-500">
            <ShieldCheck aria-hidden="true" className="h-6 w-6" />
          </span>
          <div>
            <p className="font-bold">Renewi Access</p>
            <p className="text-xs text-slate-400">Vlaardingen manager demo</p>
          </div>
        </div>
        <div className="relative my-auto max-w-xl">
          <StatusBadge tone="demo">Deterministic local environment</StatusBadge>
          <h1 className="mt-6 text-4xl font-semibold leading-tight tracking-tight">
            Manage site access in one workspace.
          </h1>
          <p className="mt-5 text-base leading-7 text-slate-300">
            Sign in with the administrator demo account to explore site access,
            invitations, and gate workflows.
          </p>
        </div>
        <p className="relative text-xs text-slate-500">
          All identities and organizations in this environment are fictional.
        </p>
      </section>

      <section className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-xl">
          <div className="lg:hidden">
            <StatusBadge tone="demo">Renewi Access demo</StatusBadge>
          </div>
          <p className="eyebrow mt-6 lg:mt-0">Batch 1 · Secure workspace</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
            Sign in to continue
          </h2>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Sign in with your work email and password. In this demonstration the
            administrator account below is filled in for you.
          </p>

          <div className="mt-6 grid gap-2 sm:grid-cols-2">
            {accounts.map(([handle, label]) => (
              <button
                aria-pressed={selectedHandle === handle}
                className={`flex items-center gap-3 rounded-xl border bg-white px-3 py-3 text-left transition hover:border-emerald-300 hover:bg-emerald-50/40 focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:ring-offset-2 ${
                  selectedHandle === handle ? "border-emerald-400 bg-emerald-50/60" : ""
                }`}
                key={handle}
                onClick={() => form.setValue("handle", handle, { shouldValidate: true })}
                type="button"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-700">
                  <UserRoundCheck aria-hidden="true" className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {label}
                  </span>
                  <span className="block text-xs text-muted-foreground">{handle}</span>
                </span>
              </button>
            ))}
          </div>
          <p aria-live="polite" className="sr-only">
            Selected demo account: {selectedHandle}
          </p>

          <form
            className="surface mt-6 space-y-5 p-5 sm:p-6"
            onSubmit={form.handleSubmit(onSubmit)}
          >
            <div>
              <label className="text-sm font-semibold text-slate-800" htmlFor="handle">
                Email
              </label>
              <input
                aria-describedby={form.formState.errors.handle ? "handle-error" : undefined}
                aria-invalid={Boolean(form.formState.errors.handle)}
                className="mt-2 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-600/20"
                id="handle"
                autoComplete="username"
                {...form.register("handle")}
              />
              {form.formState.errors.handle ? (
                <p className="mt-1 text-xs text-red-700" id="handle-error" role="alert">
                  {form.formState.errors.handle.message}
                </p>
              ) : null}
            </div>
            <div>
              <label className="text-sm font-semibold text-slate-800" htmlFor="password">
                Password
              </label>
              <input
                aria-describedby={form.formState.errors.password ? "password-error" : undefined}
                aria-invalid={Boolean(form.formState.errors.password)}
                className="mt-2 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-slate-950 focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-600/20"
                id="password"
                autoComplete="current-password"
                type="password"
                {...form.register("password")}
              />
              {form.formState.errors.password ? (
                <p className="mt-1 text-xs text-red-700" id="password-error" role="alert">
                  {form.formState.errors.password.message}
                </p>
              ) : null}
            </div>
            <div className="text-right">
              <Link className="text-xs font-semibold text-emerald-800 underline" href="/forgot-password">
                Forgot password?
              </Link>
            </div>
            {form.formState.errors.root ? (
              <div
                className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
                role="alert"
              >
                {form.formState.errors.root.message}
              </div>
            ) : null}
            <button
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-wait disabled:opacity-60"
              disabled={form.formState.isSubmitting}
              type="submit"
            >
              {form.formState.isSubmitting ? "Signing in…" : "Sign in"}
              <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
