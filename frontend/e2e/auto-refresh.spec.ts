/**
 * Auto-refresh: the dashboard keeps itself current on a timer.
 *
 * The two timers are deliberately independent and cost wildly different
 * amounts — a Clover sync is 2 Clover API requests, a list poll is a local DB
 * read. The backend once tripped Clover's 429 limit by making ~100 calls in a
 * single refresh (.claude/feature-map.md, trap 2), so the test that matters
 * most here is the one asserting the cheap poll never drags the expensive sync
 * along with it.
 *
 * 10 minutes is far too long to wait out, so these drive Playwright's fake
 * clock instead. Note `fastForward()` fires due timers *at most once* — it
 * models a closed laptop lid, not a running poll — so the stepping test below
 * advances one interval at a time rather than making one big jump.
 */

import { test, expect, type Page } from "@playwright/test";
import { signIn, stubSync, watchForProblems } from "./support/harness";

/**
 * A fixed time-of-day, so a run near midnight cannot fast-forward across a day
 * boundary and make `isToday()` in Dashboard.tsx file every order under "older".
 * Same calendar day as the real clock, so the session cookie and seeded data
 * stay coherent.
 */
const NOON = (() => {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  return d;
})();

const at = (offsetMinutes: number) =>
  new Date(NOON.getTime() + offsetMinutes * 60_000).toISOString();

interface StubOrder {
  id: number;
  clover_order_id: string;
  customer_name: string;
  customer_phone: string;
  items_summary: string;
  status: "pending" | "notified" | "cancelled";
  created_at: string;
  notified_at: string | null;
  notification_count: number;
}

const PAD_THAI = "Pad Thai x2, Thai Tea";
const MANGO = "Mango Sticky Rice";

function order(id: number, itemsSummary: string, createdAt: string): StubOrder {
  return {
    id,
    clover_order_id: `E2E0000${id}`,
    customer_name: "Som Chai",
    customer_phone: "+13145551234",
    items_summary: itemsSummary,
    status: "pending",
    created_at: createdAt,
    notified_at: null,
    notification_count: 0,
  };
}

const PAD_THAI_ORDER = order(1, PAD_THAI, at(-5));
const LATE_ORDER = order(2, MANGO, at(12));

/**
 * Stub `GET /api/orders/` and hand back a way to change what the server
 * returns mid-test. The harness does not stub this endpoint, because every
 * other spec reads the real seeded database; auto-refresh is about *when* the
 * list is fetched, so these tests need to control what a later fetch sees.
 *
 * Matched by pathname rather than a glob: a glob would have to be trusted not
 * to also catch `/api/orders/sync/`.
 */
async function stubOrders(page: Page, onCall: () => void) {
  const state = { extra: [] as StubOrder[] };

  await page.route(
    (url) => url.pathname === "/api/orders/",
    (route) => {
      onCall();
      const results = [PAD_THAI_ORDER, ...state.extra];
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: results.length, results }),
      });
    }
  );

  return state;
}

test("a new order appears on its own, without clicking Refresh", async ({ page }) => {
  await page.clock.install({ time: NOON });

  const server = await stubOrders(page, () => {});
  await stubSync(page);
  await signIn(page);

  await expect(page.getByText(PAD_THAI)).toBeVisible();
  await expect(page.getByText(MANGO)).toBeHidden();

  // The server now holds an order this dashboard has never seen.
  server.extra = [LATE_ORDER];

  // Jump past the default 10-minute list interval.
  await page.clock.fastForward("11:00");

  await expect(page.getByText(MANGO)).toBeVisible();
});

test("the cheap list poll never re-syncs Clover", async ({ page }) => {
  await page.clock.install({ time: NOON });

  const problems = watchForProblems(page);

  let listCalls = 0;
  await stubOrders(page, () => {
    listCalls += 1;
  });

  let syncCalls = 0;
  await stubSync(page, {
    onCall: () => {
      syncCalls += 1;
    },
  });

  await signIn(page);
  await expect(page.getByText(PAD_THAI)).toBeVisible();
  // Refresh is disabled while syncing — enabled means the mount cycle finished.
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true })
  ).toBeEnabled();

  const syncsAfterMount = syncCalls;
  const listsAfterMount = listCalls;
  expect(syncsAfterMount).toBe(1);

  // Drive the list interval down to its 1-minute floor and leave Clover at 10 —
  // the only way to tell the two cadences apart, since both default to 10.
  await page.getByRole("button", { name: "Auto-refresh settings" }).click();
  const listInput = page.getByLabel("Order list interval (minutes)");
  await expect(listInput).toBeVisible();
  await listInput.fill("1");
  await listInput.blur();

  // Step, don't jump: fastForward fires a due timer at most once, so one big
  // jump would produce a single tick and prove nothing about the cadence.
  for (let minute = 1; minute <= 5; minute += 1) {
    await page.clock.fastForward("01:00");
    await expect.poll(() => listCalls).toBe(listsAfterMount + minute);
  }

  // Five list polls happened; Clover was not asked once.
  expect(syncCalls).toBe(syncsAfterMount);

  // A background tick must not announce itself. (It also must not disable the
  // Refresh button — silent mode never touches `syncing` — but that is a
  // rendering property this suite has no clean way to observe over time, so it
  // is left to the design rather than asserted weakly here.)
  await expect(page.getByText("Orders pulled from Clover")).toBeHidden();

  expect(problems).toEqual([]);
});

test("the intervals survive a reload", async ({ page }) => {
  await stubOrders(page, () => {});
  await stubSync(page);
  await signIn(page);

  await page.getByRole("button", { name: "Auto-refresh settings" }).click();
  await page.getByLabel("Order list interval (minutes)").fill("3");
  await page.getByLabel("Order list interval (minutes)").blur();

  await page.reload();

  await page.getByRole("button", { name: "Auto-refresh settings" }).click();
  await expect(page.getByLabel("Order list interval (minutes)")).toHaveValue("3");
  // Untouched, so it keeps the default.
  await expect(page.getByLabel("Clover sync interval (minutes)")).toHaveValue("10");
});
