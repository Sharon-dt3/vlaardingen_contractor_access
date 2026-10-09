import { expect, test } from "@playwright/test";
import { assertSeededDemoApiReady } from "./support/reset";

test.describe("Compose-hosted Playwright package", () => {
  test("publishes a healthy demo API and the rendered login page", async ({
    page,
    request
  }) => {
    await assertSeededDemoApiReady(request);

    await page.goto("/login");

    await expect(
      page.getByRole("heading", { name: "Sign in to continue" })
    ).toBeVisible();
    await expect(page.getByLabel("Demo account")).toBeVisible();
    await expect(page.getByLabel("Local demo password")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sign in", exact: true })
    ).toBeEnabled();
  });
});
