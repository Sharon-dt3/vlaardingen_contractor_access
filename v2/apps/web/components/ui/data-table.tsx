import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type DataTableColumn<Row> = {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right";
};

type DataTableProps<Row> = {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  getRowKey: (row: Row) => string;
  caption: string;
  className?: string;
};

// PUBLIC_INTERFACE
/**
 * Renders an accessible responsive table from typed rows and columns.
 */
export function DataTable<Row>({
  columns,
  rows,
  getRowKey,
  caption,
  className
}: DataTableProps<Row>) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b bg-slate-50/80">
            {columns.map((column) => (
              <th
                className={cn(
                  "px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500",
                  column.align === "right" && "text-right"
                )}
                key={column.key}
                scope="col"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row) => (
            <tr className="transition-colors hover:bg-slate-50/70" key={getRowKey(row)}>
              {columns.map((column) => (
                <td
                  className={cn(
                    "px-5 py-4 text-slate-700",
                    column.align === "right" && "text-right"
                  )}
                  key={column.key}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
