import { cn } from "@/lib/utils";

type SkeletonProps = React.HTMLAttributes<HTMLDivElement>;

// PUBLIC_INTERFACE
/**
 * Renders a non-interactive animated placeholder while content is loading.
 */
export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-lg bg-slate-200/80", className)}
      {...props}
    />
  );
}

// PUBLIC_INTERFACE
/**
 * Renders a reusable page-level loading composition.
 */
export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite" className="space-y-7" role="status">
      <span className="sr-only">Loading content</span>
      <div className="space-y-3 border-b pb-7">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-9 w-64 max-w-full" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }, (_, index) => (
          <div className="surface space-y-4 p-5" key={index}>
            <Skeleton className="h-10 w-10 rounded-xl" />
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </div>
        ))}
      </div>
      <Skeleton className="h-64 w-full rounded-2xl" />
    </div>
  );
}
