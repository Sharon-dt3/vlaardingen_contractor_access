import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// PUBLIC_INTERFACE
/**
 * Combines conditional class names and resolves conflicting Tailwind utilities.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
