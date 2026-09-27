import { defineConfig, devices } from "@playwright/test";

// The E2E stack runs on its own ports so a dev server can be running at the
// same time: API on 8001 (dev uses 8000), preview build on 4173 (dev uses 5173).
const BACKEND_PORT = 8001;
const PREVIEW_PORT = 4173;
const BACKEND = `http://127.0.0.1:${BACKEND_PORT}`;
const PREVIEW = `http://127.0.0.1:${PREVIEW_PORT}`;

export default defineConfig({
  testDir: "./e2e",

  // These tests share one seeded sqlite database, and the SMS test mutates an
  // order, so they run one at a time.
  fullyParallel: false,
  workers: 1,

  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: PREVIEW,
    trace: "retain-on-failure",
    // A screenshot on failure is read directly when diagnosing — both by a
    // person and by an agent, which can look at the PNG rather than infer the
    // layout from the DOM.
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // Migrates a throwaway sqlite database, seeds it, and serves the API.
      // Blank credentials there mean no real SMS or Clover call can escape.
      command: "node ../scripts/e2e-backend.mjs",
      // /admin/login/ because it returns 200 — the API root is auth-gated.
      url: `${BACKEND}/admin/login/`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The production build, not the dev server: React StrictMode double-invokes
      // effects in development only, which would double every mount-time request
      // and make the request-count assertion below meaningless.
      //
      // build:e2e, not build — it passes --mode e2e so .env.production is not
      // loaded. Without that the bundle bakes in the absolute production API URL
      // and the whole suite runs against production. dist-e2e keeps the real
      // dist/ untouched so an E2E run can never clobber a deployable build.
      //
      // --host 127.0.0.1 is load-bearing: vite preview binds to "localhost" by
      // default, which on Windows can resolve to IPv6 ::1, leaving the IPv4
      // address Playwright probes unreachable.
      command: `npm run build:e2e && npm run preview -- --outDir dist-e2e --port ${PREVIEW_PORT} --strictPort --host 127.0.0.1`,
      url: PREVIEW,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
