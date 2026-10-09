"use client";

import { useQuery, type QueryKey } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PermissionBoundary } from "@/components/auth/permission-boundary";
import { EmptyState, ErrorState, PermissionState } from "@/components/states/content-state";
import {
  DataTable,
  type DataTableColumn
} from "@/components/ui/data-table";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { apiRequest, ApiError } from "@/lib/api-client";

type RecordCollectionProps<Row> = {
  permission: string;
  queryKey: QueryKey;
  endpoint: string;
  eyebrow: string;
  title: string;
  description: string;
  caption: string;
  emptyTitle: string;
  emptyDescription: string;
  columns: DataTableColumn<Row>[];
  getRowKey: (row: Row) => string;
  actions?: ReactNode;
};

// PUBLIC_INTERFACE
/**
 * Loads and renders a protected Batch 1 collection with all standard page states.
 */
export function RecordCollection<Row>({
  permission,
  queryKey,
  endpoint,
  eyebrow,
  title,
  description,
  caption,
  emptyTitle,
  emptyDescription,
  columns,
  getRowKey,
  actions
}: RecordCollectionProps<Row>) {
  return (
    <PermissionBoundary permission={permission}>
      <CollectionContent
        actions={actions}
        caption={caption}
        columns={columns}
        description={description}
        emptyDescription={emptyDescription}
        emptyTitle={emptyTitle}
        endpoint={endpoint}
        eyebrow={eyebrow}
        getRowKey={getRowKey}
        queryKey={queryKey}
        title={title}
      />
    </PermissionBoundary>
  );
}

function CollectionContent<Row>({
  queryKey,
  endpoint,
  eyebrow,
  title,
  description,
  caption,
  emptyTitle,
  emptyDescription,
  columns,
  getRowKey,
  actions
}: Omit<RecordCollectionProps<Row>, "permission">) {
  const query = useQuery({
    queryKey,
    queryFn: () => apiRequest<Row[]>(endpoint),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
      failureCount < 1
  });

  if (query.isLoading) {
    return <PageSkeleton />;
  }

  if (query.error instanceof ApiError && query.error.status === 403) {
    return <PermissionState description={query.error.message} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        description={
          query.error instanceof ApiError ? query.error.message : undefined
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  const rows = query.data ?? [];

  return (
    <div className="space-y-7">
      <PageHeader
        actions={actions}
        badge={<StatusBadge tone="success">{rows.length} loaded</StatusBadge>}
        description={description}
        eyebrow={eyebrow}
        title={title}
      />
      {rows.length === 0 ? (
        <EmptyState description={emptyDescription} title={emptyTitle} />
      ) : (
        <section className="surface overflow-hidden">
          <DataTable
            caption={caption}
            columns={columns}
            getRowKey={getRowKey}
            rows={rows}
          />
        </section>
      )}
    </div>
  );
}
