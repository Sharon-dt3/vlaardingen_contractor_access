"use client";

import { RecordCollection } from "@/components/records/record-collection";
import type { DataTableColumn } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { AuditEvent } from "@/lib/domain";
import { enumLabel, formatDateTime } from "@/lib/domain";

const columns: DataTableColumn<AuditEvent>[] = [
  {
    key: "event",
    header: "Event",
    cell: (event) => (
      <div>
        <p className="font-semibold text-slate-950">{event.action}</p>
        <p className="mt-1 max-w-xl text-xs leading-5 text-muted-foreground">
          {event.reason}
        </p>
      </div>
    )
  },
  {
    key: "entity",
    header: "Entity",
    cell: (event) => (
      <div>
        <StatusBadge tone="neutral">{enumLabel(event.entity_type)}</StatusBadge>
        <p className="mt-2 max-w-40 truncate font-mono text-xs text-muted-foreground">
          {event.entity_id}
        </p>
      </div>
    )
  },
  {
    key: "actor",
    header: "Actor",
    cell: (event) =>
      event.actor_id ? (
        <span className="font-mono text-xs">{event.actor_id.slice(0, 8)}…</span>
      ) : (
        <span className="text-sm text-muted-foreground">System seed</span>
      )
  },
  {
    key: "time",
    header: "Occurred",
    align: "right",
    cell: (event) => formatDateTime(event.occurred_at)
  }
];

// PUBLIC_INTERFACE
/**
 * Lists chronological append-only audit evidence for authorized roles.
 */
export default function AuditPage() {
  return (
    <RecordCollection
      caption="Chronological audit events"
      columns={columns}
      description="Immutable lifecycle evidence is shown oldest to newest. Write capability remains API-enforced and is not exposed by this read surface."
      emptyDescription="Audit evidence will appear here after seed or workflow actions."
      emptyTitle="No audit evidence is available"
      endpoint="/api/audit/events"
      eyebrow="Assurance evidence"
      getRowKey={(event) => event.id}
      permission="audit:read"
      queryKey={["records", "audit-events"]}
      title="Audit trail"
    />
  );
}
