import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none",
  {
    variants: {
      tone: {
        neutral: "border-slate-200 bg-slate-50 text-slate-700",
        info: "border-blue-200 bg-blue-50 text-blue-700",
        success: "border-emerald-200 bg-emerald-50 text-emerald-700",
        warning: "border-amber-200 bg-amber-50 text-amber-800",
        danger: "border-red-200 bg-red-50 text-red-700",
        demo: "border-teal-200 bg-teal-50 text-teal-800"
      }
    },
    defaultVariants: {
      tone: "neutral"
    }
  }
);

export type StatusTone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

type StatusBadgeProps = {
  children: React.ReactNode;
  className?: string;
  tone?: StatusTone;
};

// PUBLIC_INTERFACE
/**
 * Renders a compact, text-labeled status that never relies on color alone.
 */
export function StatusBadge({
  children,
  className,
  tone = "neutral"
}: StatusBadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)}>
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}
