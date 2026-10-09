import { expect, test } from "@playwright/test";
import { hasBaselineRunner, restoreSeedBaseline } from "./support/baseline";
import { loginAsSeededRole } from "./support/auth";

test.describe.configure({ mode: "serial" });

test.describe("authenticated manager acceptance walkthrough", () => {
  test.beforeEach(async ({ request }) => {
    test.skip(
      !hasBaselineRunner(),
      "The private E2E baseline runner must restore the deterministic manager walkthrough state."
    );

    await restoreSeedBaseline(request);
  });

  test.afterEach(async ({ request }) => {
    if (hasBaselineRunner()) {
      await restoreSeedBaseline(request);
    }
  });

  test("manager receives desktop permission context and server-confirmed expiry feedback", async ({
    page
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAsSeededRole(page, "manager");

    await expect(page.getByText("Authorized session", { exact: true })).toBeVisible();
    await expect(page.getByText("Site Manager", { exact: true }).first()).toBeVisible();

    const navigation = page.getByRole("navigation", {
      name: "Primary navigation"
    });
    await expect(navigation.getByRole("link", { name: "Overview" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "Visits" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "Gate kiosk" })).toHaveCount(0);
    await expect(navigation.getByRole("link", { name: "Settings" })).toHaveCount(0);

    await expect(
      page.getByRole("heading", { name: "Expiry control workspace" })
    ).toBeVisible();
    await expect(
      page.getByText(
        "Alerts, renewal tasks, compliance effects, and gate eligibility remain server-authoritative. This workspace only displays protected API state and submits permitted commands.",
        { exact: true }
      )
    ).toBeVisible();

    const processExpiryResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/expiry/process" &&
        response.request().method() === "POST"
    );

    await page.getByRole("button", { name: "Process expiry" }).click();

    const response = await processExpiryResponse;
    expect(
      response.ok(),
      "The manager's permitted expiry command must be accepted by the authoritative API."
    ).toBe(true);

    await expect(
      page
        .getByRole("status")
        .filter({
          hasText:
            "Expiry processing completed. Server-returned results are shown below."
        })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Expiry control workspace" })
    ).toBeVisible();
  });

  test("manager tablet navigation dialog restores focus after Escape", async ({ page }) => {
    await page.setViewportSize({ width: 1023, height: 800 });
    await loginAsSeededRole(page, "manager");

    const openNavigation = page.getByRole("button", {
      name: "Open navigation"
    });
    await expect(openNavigation).toBeVisible();

    await openNavigation.click();

    const navigationDialog = page.getByRole("dialog", {
      name: "Primary navigation"
    });
    await expect(navigationDialog).toBeVisible();

    const closeNavigation = navigationDialog.getByRole("button", {
      name: "Close navigation"
    });
    await expect(closeNavigation).toBeFocused();

    const mobileNavigation = navigationDialog.getByRole("navigation", {
      name: "Primary navigation"
    });
    await expect(mobileNavigation.getByRole("link", { name: "Overview" })).toBeVisible();
    await expect(mobileNavigation.getByRole("link", { name: "Audit trail" })).toBeVisible();
    await expect(mobileNavigation.getByRole("link", { name: "Gate kiosk" })).toHaveCount(0);
    await expect(mobileNavigation.getByRole("link", { name: "Settings" })).toHaveCount(0);

    await page.keyboard.press("Escape");

    await expect(navigationDialog).toBeHidden();
    await expect(openNavigation).toBeFocused();
  });
});
