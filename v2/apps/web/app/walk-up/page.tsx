"use client";

import Link from "next/link";
import { RecordCollection } from "@/components/records/record-collection";
import { PermissionBoundary } from "@/components/auth/permission-boundary";
import type { DataTableColumn } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { WalkUpQrPanel } from "@/components/workflows/walk-up-qr-panel";
import { enumLabel, formatDateTime } from "@/lib/domain";

type Arrival = {
  id: string;
  reference: string;
  person_id: string;
  first_name: string;
  last_name: string;
  company_name: string;
  email: string;
  population: string;
  site_name: string;
  registered_at: string;
  rules_version: number;
  language: string;
  statement_text: string;
  admitted_at: string | null;
  exited_at: string | null;
  email_verified: boolean;
  refusal_count: number;
  last_refused_at: string | null;
};

const columns: DataTableColumn<Arrival>[] = [
  {
    key: "reference",
    header: "Reference",
    cell: (row) => <span className="font-mono text-sm font-semibold">{row.reference}</span>
  },
  {
    key: "person",
    header: "Person",
    cell: (row) => (
      <div>
        <Link
          className="font-semibold text-slate-950 hover:text-emerald-700"
          href={`/people/${row.person_id}`}
        >
          {row.first_name} {row.last_name}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">
          {row.email} · {row.email_verified ? "verified" : "not verified"}
        </p>
      </div>
    )
  },
  { key: "company", header: "Company", cell: (row) => row.company_name },
  { key: "population", header: "Type", cell: (row) => enumLabel(row.population) },
  { key: "site", header: "Site", cell: (row) => row.site_name },
  {
    key: "rules",
    header: "Life-saving rules",
    cell: (row) => (
      <div>
        <StatusBadge tone="success">Confirmed</StatusBadge>
        <p className="mt-1 text-xs text-muted-foreground">
          v{row.rules_version} · {row.language.toUpperCase()}
        </p>
      </div>
    )
  },
  {
    key: "entry",
    header: "Entry",
    cell: (row) => (
      <div>
        {row.admitted_at ? (
          <>
            <StatusBadge tone={row.exited_at ? "neutral" : "success"}>
              {row.exited_at ? "Left" : "On site"}
            </StatusBadge>
            <p className="mt-1 text-xs text-muted-foreground">
              In {formatDateTime(row.admitted_at)}
              {row.exited_at ? ` · out ${formatDateTime(row.exited_at)}` : ""}
            </p>
          </>
        ) : (
          <span className="text-xs text-muted-foreground">Not yet</span>
        )}
        {row.refusal_count > 0 ? (
          <p className="mt-1 text-xs font-semibold text-red-800">
            Refused {row.refusal_count}×
            {row.last_refused_at ? `, last ${formatDateTime(row.last_refused_at)}` : ""}
          </p>
        ) : null}
      </div>
    )
  },
  { key: "when", header: "Registered", cell: (row) => formatDateTime(row.registered_at) }
];

// PUBLIC_INTERFACE
/**
 * Staff view of the QR walk-up path: the entrance QR code and who registered through it.
 */
export default function WalkUpPage() {
  return (
    <PermissionBoundary permission="people:read">
      <div className="space-y-7">
        <WalkUpQrPanel />
        <RecordCollection<Arrival>
          caption="People who registered through the entrance QR code in the last 24 hours"
          columns={columns}
          description="People who scanned the entrance QR code, registered and confirmed that they read and understood the life-saving rules. No invitation was needed."
          emptyDescription="Nobody has registered through the QR code in the last 24 hours."
          emptyTitle="No walk-up arrivals yet"
          endpoint="/api/walk-up/registrations?since_hours=24"
          eyebrow="Walk-up arrivals"
          getRowKey={(row) => row.id}
          permission="people:read"
          queryKey={["walk-up", "registrations"]}
          title="Walk-up arrivals"
        />
      </div>
    </PermissionBoundary>
  );
}
