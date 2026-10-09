import { expect, type APIRequestContext } from "@playwright/test";

export type BaselineCommand = "reset" | "seed";
export type BaselineCommandRunner = (command: BaselineCommand) => Promise<void>;

function apiBaseUrl(): string {
  return process.env.API_BASE_URL ?? "http://api:8000";
}

// PUBLIC_INTERFACE
/**
 * Assert that the Compose-internal API reports a ready, demo-mode baseline.
 *
 * @param request - Playwright request context connected to the Compose network.
 */
export async function assertSeededDemoApiReady(
  request: APIRequestContext
): Promise<void> {
  const response = await request.get(`${apiBaseUrl()}/health`);

  expect(response.status(), "The API health endpoint must respond successfully.").toBe(
    200
  );

  const health = (await response.json()) as {
    database?: { status?: string };
    demo_mode?: boolean;
    status?: string;
  };

  expect(health.status, "The API must report ready status.").toBe("ready");
  expect(health.database?.status, "PostgreSQL must report ready status.").toBe(
    "ready"
  );
  expect(health.demo_mode, "The e2e suite is limited to demo mode.").toBe(true);
}

// PUBLIC_INTERFACE
/**
 * Reset and reseed a deterministic baseline through an explicitly supplied
 * runner, then verify the public API readiness contract.
 *
 * This helper deliberately does not add a public application API endpoint.
 * The isolated E2E Compose profile supplies its private, capability-gated
 * runner for each mutating scenario.
 *
 * @param runCommand - Executes one documented reset or seed lifecycle command.
 * @param request - Playwright request context used for the public health check.
 */
export async function resetAndSeedBaseline(
  runCommand: BaselineCommandRunner,
  request: APIRequestContext
): Promise<void> {
  await runCommand("reset");
  await runCommand("seed");
  await assertSeededDemoApiReady(request);
}
