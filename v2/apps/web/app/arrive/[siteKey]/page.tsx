import { WalkUpRegistration } from "@/components/workflows/walk-up-registration";

// PUBLIC_INTERFACE
/**
 * The page a site's QR code opens: register on arrival and confirm the life-saving rules.
 */
export default function ArrivePage({ params }: { params: { siteKey: string } }) {
  return <WalkUpRegistration siteKey={params.siteKey} />;
}
