import { AlertTriangle, Inbox, LockKeyhole, type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

type ContentStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  tone?: "neutral" | "danger" | "warning";
  className?: string;
};

function ContentState({
  icon: Icon,
  title,
  description,
  action,
  tone = "neutral",
  className
}: ContentStateProps) {
  const iconTone = {
    neutral: "bg-slate-100 text-slate-600",
    danger: "bg-red-50 text-red-700",
    warning: "bg-amber-50 text-amber-700"
  }[tone];

  return (
    <section
      aria-atomic="true"
      aria-live={tone === "danger" ? "assertive" : "polite"}
      role={tone === "danger" ? "alert" : "status"}
      className={cn("surface flex flex-col items-center px-6 py-12 text-center", className)}
    >
      <span className={cn("grid h-12 w-12 place-items-center rounded-2xl", iconTone)}>
        <Icon aria-hidden="true" className="h-6 w-6" />
      </span>
      <h2 className="mt-4 text-base font-semibold text-slate-950">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </section>
  );
}

type EmptyStateProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
};

// PUBLIC_INTERFACE
/**
 * Explains that a valid result set currently contains no records.
 */
export function EmptyState({
  title = "Nothing to show yet",
  description = "Records will appear here when the workflow reaches this stage.",
  action,
  className
}: EmptyStateProps) {
  return (
    <ContentState
      action={action}
      className={className}
      description={description}
      icon={Inbox}
      title={title}
    />
  );
}

type ErrorStateProps = {
  title?: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
};

// PUBLIC_INTERFACE
/**
 * Presents a recoverable error without exposing implementation details.
 */
export function ErrorState({
  title = "We could not load this information",
  description = "Check the local services and try again. Your current work has not been changed.",
  onRetry,
  className
}: ErrorStateProps) {
  const retryAction = onRetry ? (
    <button
      className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-950 focus:ring-offset-2"
      onClick={onRetry}
      type="button"
    >
      Try again
    </button>
  ) : undefined;

  return (
    <ContentState
      action={retryAction}
      className={className}
      description={description}
      icon={AlertTriangle}
      title={title}
      tone="danger"
    />
  );
}

type PermissionStateProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
};

// PUBLIC_INTERFACE
/**
 * Explains that the signed-in role cannot access a page or action.
 */
export function PermissionState({
  title = "Access is restricted",
  description = "Your current demo role does not have permission to view this area.",
  action,
  className
}: PermissionStateProps) {
  return (
    <ContentState
      action={action}
      className={className}
      description={description}
      icon={LockKeyhole}
      title={title}
      tone="warning"
    />
  );
}
