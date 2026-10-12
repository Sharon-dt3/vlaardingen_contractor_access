"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { apiRequest } from "@/lib/api-client";
import { formatDateTime } from "@/lib/domain";

type Staff = {
  id: string;
  display_name: string;
  email: string | null;
  handle: string;
  role: string;
  status: "invited" | "active" | "locked" | "deactivated";
  last_login_at: string | null;
  is_you: boolean;
};

type InviteResult = { user: Staff; email_sent: boolean };

const ROLE_LABEL: Record<string, string> = {
  system_admin: "Administrator",
  gate_operator: "Gate operator",
  site_manager: "Site manager",
  compliance: "Compliance",
  host: "Host",
  participant: "Participant",
  viewer: "Viewer"
};

const STATUS: Record<Staff["status"], { label: string; tone: StatusTone }> = {
  invited: { label: "Invited, no password yet", tone: "warning" },
  active: { label: "Active", tone: "success" },
  locked: { label: "Locked for 15 minutes", tone: "danger" },
  deactivated: { label: "Deactivated", tone: "neutral" }
};

const FIELD =
  "mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950";

// PUBLIC_INTERFACE
/**
 * Lets an administrator add staff, who then choose their own password from an emailed link.
 */
export function UsersWorkspace() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("gate_operator");
  const [notice, setNotice] = useState("");

  const query = useQuery({
    queryKey: ["staff"],
    queryFn: () => apiRequest<Staff[]>("/api/users")
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["staff"] });

  const invite = useMutation({
    mutationFn: () =>
      apiRequest<InviteResult>("/api/users", { method: "POST", body: { name, email, role } }),
    onSuccess: async (result) => {
      setNotice(
        result.email_sent
          ? `An invitation was emailed to ${result.user.email}. The link works once and expires in 48 hours.`
          : `${result.user.display_name} was added, but the email could not be sent. Use Resend invitation once email is working.`
      );
      setName("");
      setEmail("");
      await refresh();
    },
    onError: () => setNotice("")
  });

  const act = useMutation({
    mutationFn: (request: { id: string; action: "resend-invitation" | "deactivate" | "reactivate" }) =>
      apiRequest<InviteResult | Staff>(`/api/users/${request.id}/${request.action}`, { method: "POST" }),
    onSuccess: async (result, request) => {
      if (request.action === "resend-invitation") {
        const sent = (result as InviteResult).email_sent;
        setNotice(sent ? "A new invitation was emailed. The earlier link no longer works." : "The email could not be sent.");
      } else {
        setNotice(request.action === "deactivate" ? "The account was deactivated. Their sessions ended." : "The account was reactivated.");
      }
      await refresh();
    }
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    invite.mutate();
  }

  const error = (invite.error ?? act.error) as Error | null;

  return (
    <div className="space-y-6">
      <section className="surface p-5 sm:p-6">
        <h2 className="text-base font-semibold text-slate-950">Add a person</h2>
        <p className="mt-1 text-sm text-slate-600">
          They get an email with a one-time link, valid for 48 hours, where they choose their own password.
          You never see it.
        </p>
        <form className="mt-4 grid gap-4 sm:grid-cols-[1fr_1fr_12rem_auto] sm:items-end" onSubmit={submit}>
          <label className="block text-sm font-semibold text-slate-700">
            Name
            <input className={FIELD} maxLength={160} minLength={2} onChange={(e) => setName(e.target.value)} required value={name} />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            Work email
            <input
              autoComplete="off"
              className={FIELD}
              maxLength={64}
              onChange={(e) => setEmail(e.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            Role
            <select className={FIELD} onChange={(e) => setRole(e.target.value)} value={role}>
              <option value="gate_operator">Gate operator</option>
              <option value="system_admin">Administrator</option>
            </select>
          </label>
          <button
            className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            disabled={invite.isPending}
            type="submit"
          >
            {invite.isPending ? "Sending" : "Send invitation"}
          </button>
        </form>
        <p className="mt-3 text-xs text-slate-500">
          Administrators can use every screen. Gate operators use the Gate kiosk.
        </p>
        {notice ? (
          <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
            {error.message}
          </p>
        ) : null}
      </section>

      <section className="surface overflow-hidden" aria-labelledby="staff-heading">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-950" id="staff-heading">
            People with access
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-3 font-semibold">Person</th>
                <th className="px-5 py-3 font-semibold">Role</th>
                <th className="px-5 py-3 font-semibold">Status</th>
                <th className="px-5 py-3 font-semibold">Last sign-in</th>
                <th className="px-5 py-3 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(query.data ?? []).map((person) => (
                <tr className="border-b border-slate-100 last:border-0" key={person.id}>
                  <td className="px-5 py-4">
                    <span className="font-semibold text-slate-950">{person.display_name}</span>
                    {person.is_you ? <span className="ml-2 text-xs text-slate-500">(you)</span> : null}
                    <span className="block text-xs text-slate-600">{person.email ?? person.handle}</span>
                  </td>
                  <td className="px-5 py-4 text-slate-700">{ROLE_LABEL[person.role] ?? person.role}</td>
                  <td className="px-5 py-4">
                    <StatusBadge tone={STATUS[person.status].tone}>{STATUS[person.status].label}</StatusBadge>
                  </td>
                  <td className="px-5 py-4 text-slate-700">
                    {person.last_login_at ? formatDateTime(person.last_login_at) : "Never"}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex flex-wrap gap-2">
                      {person.status === "invited" ? (
                        <button
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-900 disabled:opacity-50"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: person.id, action: "resend-invitation" })}
                          type="button"
                        >
                          Resend invitation
                        </button>
                      ) : null}
                      {person.status === "active" || person.status === "locked" ? (
                        person.is_you ? null : (
                          <button
                            className="rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-800 disabled:opacity-50"
                            disabled={act.isPending}
                            onClick={() => {
                              if (window.confirm(`Deactivate ${person.display_name}? They will be signed out at once.`)) {
                                act.mutate({ id: person.id, action: "deactivate" });
                              }
                            }}
                            type="button"
                          >
                            Deactivate
                          </button>
                        )
                      ) : null}
                      {person.status === "deactivated" ? (
                        <button
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-900 disabled:opacity-50"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: person.id, action: "reactivate" })}
                          type="button"
                        >
                          Reactivate
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
