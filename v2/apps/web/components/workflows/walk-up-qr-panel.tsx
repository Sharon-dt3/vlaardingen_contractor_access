"use client";

import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";

type SiteLink = { site_key: string; site_name: string; arrival_url: string };

// PUBLIC_INTERFACE
/**
 * Shows each site's printable QR code and the link it opens, for staff to put on the entrance sign.
 */
export function WalkUpQrPanel() {
  const query = useQuery({
    queryKey: ["walk-up", "sites"],
    queryFn: () => apiRequest<SiteLink[]>("/api/walk-up/sites")
  });

  if (!query.data || query.data.length === 0) return null;

  return (
    <section aria-labelledby="walk-up-qr-heading" className="surface p-5 sm:p-6">
      <h2 className="text-lg font-semibold text-slate-950" id="walk-up-qr-heading">
        Entrance QR code
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Print this and put it at the entrance. Anyone who scans it opens the registration page for
        that site. The code identifies the site only, never a person.
      </p>
      <div className="mt-4 flex flex-wrap gap-6">
        {query.data.map((site) => (
          <figure className="w-56" key={site.site_key}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt={`QR code for ${site.site_name}`}
              className="h-56 w-56 rounded-lg border bg-white p-2"
              src={`/api/walk-up/qr.png?site=${encodeURIComponent(site.site_key)}`}
            />
            <figcaption className="mt-2 text-sm">
              <span className="font-semibold text-slate-950">{site.site_name}</span>
              <a
                className="mt-1 block break-all text-xs text-emerald-800 underline"
                href={site.arrival_url}
                rel="noreferrer"
                target="_blank"
              >
                {site.arrival_url}
              </a>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
