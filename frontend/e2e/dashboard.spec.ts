/**
 * Baseline end-to-end coverage for the dashboard, in a real browser.
 *
 * This is the piece that answers "did the dashboard actually work" — a question
 * no backend test can answer, because the frontend is where staff live.
 *
 * Two things never leave this machine: Clover and Twilio are both intercepted by
 * the harness below, and `scripts/e2e-backend.mjs` blanks their credentials anyway
 * so a mis-registered route still cannot send a real text message.
 *
 * For reproducing a *specific* reported bug, don't add to this file — see the
 * /reproduce-bug skill.
 */

import { test, expect } from "@playwright/test";
import {
  OLDER_PENDING,
  TODAY_NOTIFIED,
  TODAY_PENDING,
  signIn,
  stubSend,
  stubSync,
  watchForProblems,
} from "./support/harness";

test("renders the seeded orders, grouping older ones behind the toggle", async ({ page }) => {
  await stubSync(page);
  await signIn(page);

  await expect(page.getByText(TODAY_PENDING)).toBeVisible();
  await expect(page.getByText(TODAY_NOTIFIED)).toBeVisible();
  // The 3-day-old order is not rendered at all until the toggle is clicked.
  await expect(page.getByText(OLDER_PENDING)).toBeHidden();
  await expect(
    page.getByRole("button", { name: /show 1 older order/i })
  ).toBeVisible();
});

test("the older-orders toggle reveals them", async ({ page }) => {
  await stubSync(page);
  await signIn(page);

  await page.getByRole("button", { name: /show 1 older order/i }).click();

  await expect(page.getByText(OLDER_PENDING)).toBeVisible();
  await expect(
    page.getByRole("button", { name: /hide older orders/i })
  ).toBeVisible();
});

test("opening the dashboard syncs exactly once", async ({ page }) => {
  // Guards the frontend contract that a page load is one sync, not one per
  // component. Mirrors the backend's SYNC_ORDER_CAP / lock tests from the other
  // side: those pin the cost of a sync, this pins how many get started.
  let syncCalls = 0;
  await stubSync(page, {
    onCall: () => {
      syncCalls += 1;
    },
  });

  await signIn(page);
  await expect(page.getByText(TODAY_PENDING)).toBeVisible();
  // Refresh is disabled while syncing — enabled means the cycle has finished.
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true })
  ).toBeEnabled();

  expect(syncCalls).toBe(1);
});

test("a failing Clover sync does not blank the dashboard", async ({ page }) => {
  // Deliberate, documented behaviour: staff must still see local orders when
  // Clover is down. A regression here turns a degraded sync into a dead screen.
  await page.route("**/api/orders/sync/", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: "Clover API token not configured." }),
    })
  );

  await signIn(page);

  await expect(page.getByText(TODAY_PENDING)).toBeVisible();
  await expect(page.getByText("Clover sync failed", { exact: true })).toBeVisible();
});

test("sending an SMS marks the order notified without texting anyone", async ({ page }) => {
  await stubSync(page);

  let sendCalls = 0;
  await stubSend(page, {
    onCall: () => {
      sendCalls += 1;
    },
  });

  await signIn(page);

  // Scoped to the card we clicked. The seeded fixture already contains a
  // notified order, so an unscoped "SMS sent" matches two elements.
  const card = page.getByTestId("order-card").filter({ hasText: TODAY_PENDING });
  await card.getByRole("button", { name: "Send SMS" }).click();

  await expect(card.getByText("SMS sent", { exact: true })).toBeVisible();
  expect(sendCalls).toBe(1);
});

test("loads without console errors or uncaught exceptions", async ({ page }) => {
  const problems = watchForProblems(page);

  await stubSync(page);
  await signIn(page);
  await expect(page.getByText(TODAY_PENDING)).toBeVisible();

  expect(problems).toEqual([]);
});

test("never calls an API outside the local origin", async ({ page }) => {
  // A regression guard with teeth: the E2E build once inherited VITE_API_URL
  // from .env.production, which pointed the entire suite — the login POST
  // included — at the real production API. Static assets such as web fonts are
  // fine; API traffic is not.
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    const isLocal = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    if (!isLocal && url.pathname.includes("/api/")) {
      external.push(request.url());
    }
  });

  await stubSync(page);
  await signIn(page);
  await expect(page.getByText(TODAY_PENDING)).toBeVisible();

  expect(external).toEqual([]);
});
