---
name: reproduce-bug
description: Reproduce a reported bug as a failing browser test, read the captured evidence, fix it, and leave the test behind as a regression guard. Use when given a symptom to investigate in the dashboard.
---

Turn a symptom into a failing test, fix it, and keep the test.

**Project root:** `C:\Users\meanp\Desktop\VSCODE\chiang-mai\chiang-mai-notification`

The point of doing it this way rather than poking at the app by hand: a reproduction that
fails is *proof* you found the bug, a passing one is *proof* you fixed it, and the test
stays behind so the bug can never come back quietly.

## The loop

### 1. Turn the report into a falsifiable claim

This is the step that decides whether the rest works. "The dashboard is broken" is not
testable. Rewrite it as: **given** some state, **when** some action, **then** some
observable outcome.

| Report | Claim |
|---|---|
| "Send doesn't work sometimes" | Given an order with no phone, the Send button is disabled |
| "Orders disappear" | Given a pending order, after Refresh it is still listed |
| "Wrong day" | Given an order created 10 minutes ago, it appears under Today |

If you cannot phrase it that way, you do not yet understand the report well enough to
fix it — go read `../feature-map.md` and ask for the missing detail.

### 2. Shape the data, if the bug depends on it

The default fixture may not contain the state you need. Write a scenario file:

```json
{
  "orders": [
    {
      "clover_order_id": "BUG00001",
      "customer_name": "No Phone",
      "customer_phone": "",
      "items_summary": "Pad Thai x2",
      "status": "pending",
      "minutes_ago": 10
    }
  ]
}
```

Save it under `frontend/e2e/scenarios/`, then point the run at it. `minutes_ago`
backdates `created_at` (1440 = one day); everything except `clover_order_id` is optional.
Valid statuses: `pending`, `notified`, `cancelled`.

```bash
E2E_SEED_JSON=frontend/e2e/scenarios/my-case.json npx playwright test e2e/my-repro.spec.ts
```

The path is resolved from the repo root. Orders **cannot** be created through the API —
the serializers are read-only — so seeding is the only way to put data in front of the
dashboard.

### 3. Write the spec, asserting the behaviour that *should* happen

Copy this shape. It must fail while the bug exists.

```ts
import { test, expect } from "@playwright/test";
import { signIn, stubSync, watchForProblems, shot } from "./support/harness";

test("an order with no phone cannot be sent", async ({ page }, testInfo) => {
  const problems = watchForProblems(page);   // console errors + failed requests
  await stubSync(page);

  await signIn(page);

  const card = page.getByTestId("order-card").filter({ hasText: "Pad Thai x2" });

  await shot(page, testInfo, "before-click");       // look at this afterwards
  await expect(card.getByRole("button", { name: "Send SMS" })).toBeDisabled();
  expect(problems).toEqual([]);
});
```

Run only your spec — do not run the whole suite while iterating:

```bash
cd frontend && npx playwright test e2e/my-repro.spec.ts
```

### 4. Read the evidence

| What | Where |
|---|---|
| **Page snapshot — read this first** | `frontend/test-results/<test-name>/error-context.md` |
| Screenshot on failure | `frontend/test-results/<test-name>/test-failed-1.png` |
| Your own `shot()` captures | `frontend/test-results/<test-name>/*.png` |
| Backend logs | lines prefixed `[WebServer]` in the test output |
| Full timeline (for a person) | `npx playwright show-trace frontend/test-results/<test-name>/trace.zip` |

**Open the PNG.** Screenshots can be viewed directly — a layout or state bug is often
obvious from the picture in a way the DOM dump is not.

### 5. Fix, then confirm red → green

Re-run the same spec. If it passes without your fix, the test was not reproducing the bug
— go back to step 1.

### 6. Decide what to keep

- Bug was real and worth guarding → leave the spec in `e2e/`, named for the behaviour (not
  `<ticket>-repro`). Keep its scenario file too.
- It was a one-off data problem → delete the spec, and say what you found.
- You edited `seed_e2e.py` or the harness to make it work → that's fine, and it makes the
  next reproduction cheaper.

Then run the real gate: `python scripts/check.py --e2e`.

## Rules

- **Never let a real SMS out.** Use `stubSend()` from the harness. The E2E backend also
  blanks Twilio/Clover credentials, but do not rely on that as the only layer.
- **Scope assertions to a card.** `page.getByTestId("order-card").filter({ hasText: ... })`.
  The seeded fixture already contains a notified order, so an unscoped "SMS sent" matches
  two elements and fails on a strict-mode violation that looks like a real bug.
- **Don't assert on counts of requests without checking what's expected.** A page load
  fires two `GET /api/orders/` (one to paint local orders, one to reload after the sync)
  and exactly one `POST /api/orders/sync/`. Both are deliberate — see the comment in
  `src/hooks/useOrders.ts`.
- **Two known-benign signals are already filtered** by `watchForProblems`: the browser's
  generic "Failed to load resource" line, and the app's unauthenticated `/api/me/` 403
  session probe. Don't re-add them as failures.
- **A failing test is a finding, not an obstacle.** If the spec fails for a reason you did
  not expect, that is usually the actual bug. Read it before working around it.
