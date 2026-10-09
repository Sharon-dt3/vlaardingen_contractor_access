"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/states/content-state";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

// PUBLIC_INTERFACE
/**
 * Presents a recoverable route error without exposing stack or service details.
 */
export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    console.error("Route rendering failed", error);
  }, [error]);

  return (
    <ErrorState
      description="The page encountered an unexpected issue. The navigation and your current demo data remain available."
      onRetry={reset}
      title="This page needs to be reloaded"
    />
  );
}
