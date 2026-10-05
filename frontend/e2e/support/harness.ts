/**
 * Shared plumbing for E2E specs.
 *
 * Writing a reproduction should be about describing the symptom, not about
 * re-deriving how to sign in or how to stub Clover. Everything a spec needs for
 * that lives here.
 *
 * Not a spec itself — Playwright's testMatch only collects *.spec.ts, so nothing
 * in this file runs on its own.
 */

import path from "path";
import { expect, type Page, type TestInfo } from "@playwright/test";

export const E2E_USERNAME = "e2e-staff";
export const E2E_PASSWORD = "e2e-password";

/** The default seeded orders, from orders/management/commands/seed_e2e.py. */
export const TODAY_PENDING = "Pad Thai x2, Thai Tea";
export const TODAY_NOTIFIED = "Green Curry";
export const OLDER_PENDING = "Pad See Ew";

export const EMPTY_SYNC = { created: 0, updated: 0, skipped: 0, errors: 0 };

/** Sign in and wait until the dashboard is up. */
export async function signIn(page: Page) {
  await page.goto("/");
  await page.locator("#username").fill(E2E_USERNAME);
  await page.locator("#password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // exact: role-name matching is substring-based by default, so a plain
  // "Refresh" also hits the "Auto-refresh settings" button beside it.
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true })
  ).toBeVisible();
}

/**
 * Stub the Clover sync. Call this BEFORE navigating — mount fires it.
 *
 * `onCall` is the hook for counting requests, which is how the suite asserts
 * that a page load syncs once rather than once per component.
 */
export async function stubSync(
  page: Page,
  options: { result?: typeof EMPTY_SYNC; onCall?: () => void } = {}
) {
  const result = options.result ?? EMPTY_SYNC;
  await page.route("**/api/orders/sync/", (route) => {
    options.onCall?.();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
}

/** Stub the SMS send so no message can leave the machine. */
export async function stubSend(
  page: Page,
  options: {
    status?: "sent" | "failed";
    errorMessage?: string | null;
    onCall?: () => void;
  } = {}
) {
  const status = options.status ?? "sent";
  await page.route("**/api/orders/*/send/", (route) => {
    options.onCall?.();
    return route.fulfill({
      status: status === "sent" ? 200 : 502,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        order: 1,
        recipient_phone: "+13145551234",
        message_body: "stubbed by the E2E harness",
        status,
        twilio_sid: status === "sent" ? "SM_STUBBED" : null,
        error_message: options.errorMessage ?? null,
        created_at: new Date().toISOString(),
      }),
    });
  });
}

/**
 * Collect everything that went wrong during a test: uncaught exceptions, app
 * console errors, and failed HTTP responses.
 *
 * Two known-benign signals are filtered, both deliberate:
 *   - the browser's generic "Failed to load resource" line, because the response
 *     listener below reports the same failure with its URL and status attached;
 *   - the 403 from the app's unauthenticated /api/me/ session probe, which is how
 *     it decides to show the sign-in page.
 *
 * Returns a live array — read it after the interaction you care about.
 */
export function watchForProblems(page: Page): string[] {
  const problems: string[] = [];

  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    if (msg.text().includes("Failed to load resource")) return;
    problems.push(`console: ${msg.text()}`);
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const { pathname } = new URL(response.url());
    const sessionProbe = pathname === "/api/me/" && response.status() === 403;
    if (!sessionProbe) {
      problems.push(`http ${response.status()}: ${response.url()}`);
    }
  });

  return problems;
}

/**
 * Save a full-page screenshot and return its path.
 *
 * The point is that a *human or agent* can then look at it — read the returned
 * file directly rather than guessing from the DOM. Lands next to the test's
 * other artifacts, so it is cleaned up with them.
 */
export async function shot(page: Page, testInfo: TestInfo, name: string) {
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return path.relative(process.cwd(), file);
}
