import type { APIRequestContext } from "@playwright/test";
import { assertSeededDemoApiReady } from "./reset";

type BaselineRunnerConfiguration = {
  token: string;
  url: string;
};

function baselineRunner(): BaselineRunnerConfiguration | undefined {
  const token = process.env.E2E_BASELINE_TOKEN?.trim();
  const url = process.env.E2E_BASELINE_URL?.trim().replace(/\/$/, "");

  return token && url ? { token, url } : undefined;
}

// PUBLIC_INTERFACE
/**
 * Returns whether the current e2e invocation has supplied the documented
 * private baseline-runner configuration required for mutating scenarios.
 *
 * The runner remains separate from the application API, and is available only
 * in the disposable Compose E2E profile with a capability token.
 */
export function hasBaselineRunner(): boolean {
  return Boolean(baselineRunner());
}

// PUBLIC_INTERFACE
/**
 * Restore the private isolated reset-and-seed baseline and verify the public
 * demo-mode health contract afterward.
 *
 * @param request - Playwright request context used to verify public API health.
 * @throws Error when the runner is absent or fails to restore the baseline.
 */
export async function restoreSeedBaseline(
  request: APIRequestContext
): Promise<void> {
  const runner = baselineRunner();

  if (!runner) {
    throw new Error(
      "E2E_BASELINE_URL and E2E_BASELINE_TOKEN are required for mutating deterministic e2e scenarios."
    );
  }

  const response = await request.post(`${runner.url}/restore`, {
    headers: {
      "X-E2E-Baseline-Token": runner.token
    },
    timeout: 120_000
  });
  if (response.status() !== 204) {
    throw new Error(
      `The isolated E2E baseline runner failed with status ${response.status()}.`
    );
  }

  await assertSeededDemoApiReady(request);
}
