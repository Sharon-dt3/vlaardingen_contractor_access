import { PageSkeleton } from "@/components/ui/skeleton";

// PUBLIC_INTERFACE
/**
 * Displays the shared route placeholder while App Router content streams.
 */
export default function Loading() {
  return <PageSkeleton />;
}
