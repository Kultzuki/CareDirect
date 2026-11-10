import { defineConfig, devices } from "@playwright/test";

// Dedicated ports so tests do not collide with dev servers on 3000/8000.
const API_URL = "http://127.0.0.1:8100";
const WEB_URL = "http://127.0.0.1:3100";
const python = process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
// Explicit local-only harness: its import refuses any database except caredirect_test.
const mockedPayments = process.env.CAREDIRECT_E2E_MOCK === "1";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../output/playwright/test-results",
  // Seeds the demo payer and writes the synthetic fixture files before any test runs.
  globalSetup: "./e2e/global-setup.ts",
  // The dev server compiles each route on first use, so allow more time than the 5s default.
  expect: { timeout: 15_000 },
  // One worker: with several, tests hit different routes of the cold dev server at the same
  // time, and each first compile makes Turbopack reload pages that are already open, which
  // fails tests at random. Serial runs are stable and still finish in about a minute.
  workers: 1,
  use: {
    baseURL: WEB_URL,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn ${mockedPayments ? "tests.e2e_payment_app:app" : "app.main:app"} --host 127.0.0.1 --port 8100`,
      cwd: "../api",
      url: `${API_URL}/health`,
      // Uploads from tests go to <repo>/storage/e2e, which is gitignored and private.
      env: { STORAGE_DIR: "storage/e2e" },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3100",
      url: `${WEB_URL}/health`,
      env: { API_BASE_URL: API_URL },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
