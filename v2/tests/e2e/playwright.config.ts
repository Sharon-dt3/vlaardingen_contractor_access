import { defineConfig, devices } from "@playwright/test";

const webBaseUrl = process.env.WEB_BASE_URL ?? "http://web:3000";
const apiBaseUrl = process.env.API_BASE_URL ?? "http://api:8000";

export default defineConfig({
  testDir: ".",
  testMatch: /test_.*\.spec\.ts/,
  outputDir: "../../artifacts/batch8/playwright/test-results",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000
  },
  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: "../../artifacts/batch8/playwright/report",
        open: "never"
      }
    ]
  ],
  metadata: {
    apiBaseUrl
  },
  use: {
    baseURL: webBaseUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off"
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"]
      }
    }
  ]
});
