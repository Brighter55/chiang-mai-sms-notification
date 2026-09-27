/**
 * An order with no phone number must not be sendable.
 *
 * The API already refuses this (400, covered in orders/tests.py), but nothing
 * stopped the *button* from being clickable — which is the version of the bug
 * staff would actually hit: a click that appears to do nothing.
 *
 * Relies on the "Walk In" order (no phone) in the default seed fixture.
 */

import { test, expect } from "@playwright/test";
import { shot, signIn, stubSend, stubSync, watchForProblems } from "./support/harness";

const ITEMS = "Khao Soi";

test("an order with no phone cannot be sent", async ({ page }, testInfo) => {
  const problems = watchForProblems(page);
  await stubSync(page);

  let sendCalls = 0;
  await stubSend(page, {
    onCall: () => {
      sendCalls += 1;
    },
  });

  await signIn(page);

  const card = page.getByTestId("order-card").filter({ hasText: ITEMS });
  await expect(card).toBeVisible();
  // The card shows the "No phone" placeholder where the number would go. Asserted
  // exactly: a customer literally named "No Phone" would otherwise match too.
  await expect(card.getByText("No phone", { exact: true })).toBeVisible();

  await shot(page, testInfo, "no-phone-card");

  await expect(card.getByRole("button", { name: "Send SMS" })).toBeDisabled();
  expect(sendCalls).toBe(0);
  expect(problems).toEqual([]);
});
