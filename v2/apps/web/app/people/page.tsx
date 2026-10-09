"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { RecordCollection } from "@/components/records/record-collection";
import type { DataTableColumn } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { Person } from "@/lib/domain";
import { enumLabel, formatDateTime, lifeSavingBadge, statusTone } from "@/lib/domain";

const columns: DataTableColumn<Person>[] = [
  {
    key: "name",
    header: "Person",
    cell: (person) => (
      <div>
        <Link
          className="inline-flex items-center gap-1 font-semibold text-slate-950 hover:text-emerald-700"
          href={`/people/${person.id}`}
        >
          {person.first_name} {person.last_name}
          <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">{person.email}</p>
      </div>
    )
  },
  {
    key: "population",
    header: "Population",
    cell: (person) => enumLabel(person.population)
  },
  {
    key: "company",
    header: "Company reference",
    cell: (person) => (
      <span className="font-mono text-xs">{person.company_id.slice(0, 8)}…</span>
    )
  },
  {
    key: "life-saving-rules",
    header: "Life-saving rules",
    cell: (person) => {
      const rules = person.life_saving_rules;
      if (!rules) return <span className="text-xs text-muted-foreground">Not available</span>;
      const badge = lifeSavingBadge(rules.status);
      return (
        <div>
          <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>
          {rules.acknowledged_at ? (
            <p className="mt-1 text-xs text-muted-foreground">
              v{rules.confirmed_rules_version} · {formatDateTime(rules.acknowledged_at)}
            </p>
          ) : null}
        </div>
      );
    }
  },
  {
    key: "standing",
    header: "Standing",
    align: "right",
    cell: (person) => (
      <StatusBadge tone={statusTone(person.standing)}>
        {enumLabel(person.standing)}
      </StatusBadge>
    )
  }
];

// PUBLIC_INTERFACE
/**
 * Lists synthetic people available to the signed-in role.
 */
export default function PeoplePage() {
  return (
    <RecordCollection
      caption="Authorized people"
      columns={columns}
      description="Core synthetic person records only. Credential evidence remains outside this Batch 1 surface."
      emptyDescription="Seeded people will appear here after the deterministic demo seed runs."
      emptyTitle="No people are available"
      endpoint="/api/people"
      eyebrow="Core records"
      getRowKey={(person) => person.id}
      permission="people:read"
      queryKey={["records", "people"]}
      title="People"
    />
  );
}
