import { expect, type Page } from "@playwright/test";

export const SEEDED_ROLE_HANDLES = {
  administrator: "admin.demo",
  compliance: "sheq.demo",
  manager: "manager.demo",
  gateOperator: "gate.demo",
  host: "host.demo",
  participant: "participant.demo",
  viewer: "viewer.demo"
} as const;

export type SeededRole = keyof typeof SEEDED_ROLE_HANDLES;

function configuredDemoPassword(): string {
  const password = process.env.E2E_DEMO_PASSWORD;

  if (!password) {
    throw new Error(
      "E2E_DEMO_PASSWORD is required for a seeded-role browser login."
    );
  }

  return password;
}

// PUBLIC_INTERFACE
/**
 * Authenticate through the rendered local-demo login form using a seeded role.
 *
 * The password remains in the browser control and is never written to the test
 * output, report, trace annotation, or assertion message.
 *
 * @param page - The Playwright page that will receive the authenticated session.
 * @param role - The deterministic seeded role to authenticate as.
 */
export async function loginAsSeededRole(
  page: Page,
  role: SeededRole = "administrator"
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Demo account").fill(SEEDED_ROLE_HANDLES[role]);
  await page.getByLabel("Local demo password").fill(configuredDemoPassword());
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  await page.waitForURL((url) => url.pathname !== "/login");
  await expect(page.locator("#main-content")).toBeVisible();
}
