"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";

type SiteSettings = {
  site_id: string;
  site_key: string;
  site_name: string;
  visit_default_hours: number;
  walk_up_pass_hours: number;
  access_qr_max_hours: number;
  walk_up_entry_delay_minutes: number;
  updated_at: string | null;
};

const MAX_VISIT_HOURS = 168;
const MAX_PASS_HOURS = 72;
const MAX_QR_MAX_HOURS = 168;
const MAX_DELAY_MINUTES = 240;
const fieldClass =
  "mt-1 w-28 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950";

// PUBLIC_INTERFACE
/**
 * Lets an administrator set, for each site, the default visit length for invitations (Path A)
 * and how long a walk-up entry QR stays valid (Path B). Issued QR codes keep their expiry.
 */
export function SiteAccessSettings() {
  const query = useQuery({
    queryKey: ["site-settings"],
    queryFn: () => apiRequest<SiteSettings[]>("/api/site-settings")
  });

  if (!query.data || query.data.length === 0) return null;

  return (
    <section aria-labelledby="access-validity-heading" className="surface p-5 sm:p-6">
      <h2 className="text-base font-semibold text-slate-950" id="access-validity-heading">
        How long access lasts
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Set this for each site. New invitations and new walk-up QR codes use the new numbers. QR
        codes that were already issued keep the time they were given.
      </p>
      <div className="mt-4 space-y-5">
        {query.data.map((site) => (
          <SiteRow key={`${site.site_id}-${site.visit_default_hours}-${site.walk_up_pass_hours}-${site.access_qr_max_hours}-${site.walk_up_entry_delay_minutes}`} site={site} />
        ))}
      </div>
    </section>
  );
}

function SiteRow({ site }: { site: SiteSettings }) {
  const queryClient = useQueryClient();
  const [visit, setVisit] = useState(String(site.visit_default_hours));
  const [pass, setPass] = useState(String(site.walk_up_pass_hours));
  const [qrMax, setQrMax] = useState(String(site.access_qr_max_hours));
  const [delay, setDelay] = useState(String(site.walk_up_entry_delay_minutes));
  const visitHours = Number(visit);
  const passHours = Number(pass);
  const qrMaxHours = Number(qrMax);
  const delayMinutes = Number(delay);
  const valid =
    Number.isInteger(visitHours) &&
    visitHours >= 1 &&
    visitHours <= MAX_VISIT_HOURS &&
    Number.isInteger(passHours) &&
    passHours >= 1 &&
    passHours <= MAX_PASS_HOURS &&
    Number.isInteger(qrMaxHours) &&
    qrMaxHours >= 1 &&
    qrMaxHours <= MAX_QR_MAX_HOURS &&
    Number.isInteger(delayMinutes) &&
    delayMinutes >= 0 &&
    delayMinutes <= MAX_DELAY_MINUTES;
  const changed =
    visitHours !== site.visit_default_hours ||
    passHours !== site.walk_up_pass_hours ||
    qrMaxHours !== site.access_qr_max_hours ||
    delayMinutes !== site.walk_up_entry_delay_minutes;

  const mutation = useMutation({
    mutationFn: () =>
      apiRequest<SiteSettings>(`/api/site-settings/${encodeURIComponent(site.site_key)}`, {
        method: "PUT",
        body: {
          visit_default_hours: visitHours,
          walk_up_pass_hours: passHours,
          access_qr_max_hours: qrMaxHours,
          walk_up_entry_delay_minutes: delayMinutes
        }
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["site-settings"] })
  });

  return (
    <form
      className="rounded-xl border border-slate-200 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && changed) mutation.mutate();
      }}
    >
      <h3 className="text-sm font-semibold text-slate-950">{site.site_name}</h3>
      <div className="mt-3 flex flex-wrap gap-6">
        <label className="text-sm text-slate-700">
          Planned arrival: default visit length (hours)
          <input
            className={`${fieldClass} block`}
            inputMode="numeric"
            max={MAX_VISIT_HOURS}
            min={1}
            onChange={(event) => setVisit(event.target.value)}
            type="number"
            value={visit}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Pre-fills the end of a new invitation. 1 to {MAX_VISIT_HOURS}.
          </span>
        </label>
        <label className="text-sm text-slate-700">
          Unexpected arrival: entry QR valid for (hours)
          <input
            className={`${fieldClass} block`}
            inputMode="numeric"
            max={MAX_PASS_HOURS}
            min={1}
            onChange={(event) => setPass(event.target.value)}
            type="number"
            value={pass}
          />
          <span className="mt-1 block text-xs text-slate-500">
            How long a walk-up entry QR works after registering. 1 to {MAX_PASS_HOURS}.
          </span>
        </label>
        <label className="text-sm text-slate-700">
          Planned arrival: longest an access QR may last (hours)
          <input
            className={`${fieldClass} block`}
            inputMode="numeric"
            max={MAX_QR_MAX_HOURS}
            min={1}
            onChange={(event) => setQrMax(event.target.value)}
            type="number"
            value={qrMax}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Staff cannot issue an access QR valid for longer. 1 to {MAX_QR_MAX_HOURS}.
          </span>
        </label>
        <label className="text-sm text-slate-700">
          Unexpected arrival: entry opens after registering (minutes)
          <input
            className={`${fieldClass} block`}
            inputMode="numeric"
            max={MAX_DELAY_MINUTES}
            min={0}
            onChange={(event) => setDelay(event.target.value)}
            type="number"
            value={delay}
          />
          <span className="mt-1 block text-xs text-slate-500">
            0 means the QR works straight away. The valid hours above count from this time. 0 to {MAX_DELAY_MINUTES}.
          </span>
        </label>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <button
          className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          disabled={!valid || !changed || mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Saving" : "Save"}
        </button>
        {!valid ? (
          <span className="text-sm text-red-700">
            Enter whole numbers within the ranges shown.
          </span>
        ) : null}
        {mutation.isSuccess && !changed ? (
          <span className="text-sm text-emerald-800">Saved.</span>
        ) : null}
        {mutation.isError ? (
          <span className="text-sm text-red-700">
            {mutation.error instanceof Error ? mutation.error.message : "Could not save."}
          </span>
        ) : null}
      </div>
    </form>
  );
}
