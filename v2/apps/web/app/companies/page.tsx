"use client";

import { RecordCollection } from "@/components/records/record-collection";
import type { DataTableColumn } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { Company } from "@/lib/domain";
import { enumLabel } from "@/lib/domain";

const columns: DataTableColumn<Company>[] = [
  {
    key: "name",
    header: "Company",
    cell: (company) => (
      <div>
        <p className="font-semibold text-slate-950">{company.name}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {company.seed_key}
        </p>
      </div>
    )
  },
  {
    key: "type",
    header: "Type",
    cell: (company) => enumLabel(company.company_type)
  },
  {
    key: "country",
    header: "Country",
    cell: (company) => company.country_code
  },
  {
    key: "status",
    header: "Status",
    align: "right",
    cell: (company) => (
      <StatusBadge tone={company.is_active ? "success" : "neutral"}>
        {company.is_active ? "Active" : "Inactive"}
      </StatusBadge>
    )
  }
];

// PUBLIC_INTERFACE
/**
 * Lists fictional seeded companies available to the signed-in role.
 */
export default function CompaniesPage() {
  return (
    <RecordCollection
      caption="Authorized companies"
      columns={columns}
      description="Fictional organizations used to tell the deterministic manager-demo story."
      emptyDescription="Seeded companies will appear here after the deterministic demo seed runs."
      emptyTitle="No companies are available"
      endpoint="/api/companies"
      eyebrow="Core records"
      getRowKey={(company) => company.id}
      permission="companies:read"
      queryKey={["records", "companies"]}
      title="Companies"
    />
  );
}
