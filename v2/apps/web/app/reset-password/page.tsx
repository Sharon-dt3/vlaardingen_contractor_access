"use client";

import { PasswordLinkForm } from "@/components/users/password-link-form";

// PUBLIC_INTERFACE
/**
 * Where a person chooses a new password from a reset link they were emailed.
 */
export default function ResetPasswordPage() {
  return (
    <PasswordLinkForm
      badLinkText="This link has expired or was already used. Ask for a new one from the sign-in page."
      doneHeading="Your password was changed"
      doneText="Every other browser where you were signed in has been signed out. Sign in with your new password."
      heading="Choose a new password"
      intro={(info) => `Hello ${info.display_name}. This changes the password for ${info.email}.`}
      lookupPath="/auth/reset"
      submitPath="/auth/reset-password"
    />
  );
}
