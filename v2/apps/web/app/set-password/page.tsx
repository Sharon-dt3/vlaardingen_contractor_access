"use client";

import { PasswordLinkForm } from "@/components/users/password-link-form";

// PUBLIC_INTERFACE
/**
 * Where an invited person chooses their own password from the one-time emailed link.
 */
export default function SetPasswordPage() {
  return (
    <PasswordLinkForm
      badLinkText="This link has expired or was already used. Ask an administrator to send you a new invitation."
      doneHeading="Your account is ready"
      doneText="Sign in with your email and the password you just chose."
      heading="Choose your password"
      intro={(info) =>
        `Hello ${info.display_name}. You will sign in with ${info.email} as ${info.role_label.toLowerCase()}.`
      }
      lookupPath="/auth/invitation"
      submitPath="/auth/set-password"
    />
  );
}
