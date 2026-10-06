/**
 * The "Send Review" flow: overflow menu -> confirmation dialog -> SMS.
 *
 * Clover plays no part in this — the orders come from the seeded throwaway
 * database (orders/management/commands/seed_e2e.py) and the review POST is
 * intercepted by the harness, so nothing can text a real customer.
 *
 * The one thing these tests assert about "already asked" state comes from the
 * *real* API: the seed records a sent review against one order's phone, so the
 * dialog's warning branch is driven by actual database state rather than a stub
 * that could disagree with the backend.
 */

import { test, expect, type Page } from "@playwright/test";
import {
  CANCELLED_ITEMS,
  NO_PHONE_ITEMS,
  TODAY_NOTIFIED,
  TODAY_PENDING,
  signIn,
  stubReview,
  stubSync,
  watchForProblems,
} from "./support/harness";

/** The card for one seeded order, found by its item summary. */
const cardFor = (page: Page, items: string) =>
  page.getByTestId("order-card").filter({ hasText: items });

/** Open the card's overflow menu and hand the card back for further scoping. */
async function openMenu(page: Page, items: string) {
  const card = cardFor(page, items);
  await card.getByRole("button", { name: "More actions" }).click();
  return card;
}

test("the overflow menu sends a review request without texting anyone", async ({ page }) => {
  const problems = watchForProblems(page);
  await stubSync(page);

  let reviewCalls = 0;
  await stubReview(page, {
    onCall: () => {
      reviewCalls += 1;
    },
  });

  await signIn(page);

  const card = await openMenu(page, TODAY_PENDING);
  await page.getByRole("menuitem", { name: "Send Review" }).click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByText("Send a review request?")).toBeVisible();
  await dialog.getByRole("button", { name: "Send review" }).click();

  await expect(page.getByText("Review request sent!")).toBeVisible();
  expect(reviewCalls).toBe(1);

  // The card reflects it immediately, without waiting for the next poll.
  await expect(card.getByText(/Review sent/)).toBeVisible();

  expect(problems).toEqual([]);
});

test("the dialog warns when this customer has already been asked", async ({ page }) => {
  await stubSync(page);

  let reviewCalls = 0;
  await stubReview(page, {
    onCall: () => {
      reviewCalls += 1;
    },
  });

  await signIn(page);

  const card = await openMenu(page, TODAY_NOTIFIED);
  // This order's phone carries a seeded sent review, so the card says so before
  // staff even open the menu.
  await expect(card.getByText(/Review sent/)).toBeVisible();

  await page.getByRole("menuitem", { name: "Send Review" }).click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByText("Already sent a review")).toBeVisible();

  // Asking again is allowed — the warning is the guard, not a refusal.
  await dialog.getByRole("button", { name: "Send again" }).click();

  expect(reviewCalls).toBe(1);
});

test("cancelling the dialog sends nothing", async ({ page }) => {
  await stubSync(page);

  let reviewCalls = 0;
  await stubReview(page, {
    onCall: () => {
      reviewCalls += 1;
    },
  });

  await signIn(page);

  await openMenu(page, TODAY_PENDING);
  await page.getByRole("menuitem", { name: "Send Review" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByRole("alertdialog")).toBeHidden();
  expect(reviewCalls).toBe(0);
});

test("an order with no phone cannot request a review", async ({ page }) => {
  // The same invariant no-phone.spec.ts guards for Send SMS: a click that
  // appears to do nothing is worse than a disabled control.
  const problems = watchForProblems(page);
  await stubSync(page);

  let reviewCalls = 0;
  await stubReview(page, {
    onCall: () => {
      reviewCalls += 1;
    },
  });

  await signIn(page);

  await openMenu(page, NO_PHONE_ITEMS);

  await expect(page.getByRole("menuitem", { name: "Send Review" })).toBeDisabled();
  expect(reviewCalls).toBe(0);
  expect(problems).toEqual([]);
});

test("a cancelled order offers no overflow menu", async ({ page }) => {
  await stubSync(page);
  await signIn(page);

  // Guards against a vacuous pass: the menu does exist on other cards, so its
  // absence below is about the cancelled status and not a missing component.
  await expect(
    cardFor(page, TODAY_PENDING).getByRole("button", { name: "More actions" })
  ).toBeVisible();

  const card = cardFor(page, CANCELLED_ITEMS);
  await expect(card).toBeVisible();
  await expect(card.getByRole("button", { name: "More actions" })).toBeHidden();
});
