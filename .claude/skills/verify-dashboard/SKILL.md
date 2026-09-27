---
name: verify-dashboard
description: Verify the dashboard actually works in a real browser — login, order rendering, refresh, SMS send, console errors. Use after changing anything in frontend/ or the API it calls.
---

Prove a frontend change works by driving the real dashboard in a browser, instead of
reasoning about it from the source.

**Project root:** `C:\Users\meanp\Desktop\VSCODE\chiang-mai\chiang-mai-notification`

## Run it

```bash
cd "C:/Users/meanp/Desktop/VSCODE/chiang-mai/chiang-mai-notification/frontend" && npx playwright test
```

Or as part of every gate: `python scripts/check.py --e2e`.

The whole suite takes ~15s once browsers are installed. First time only:

```bash
cd frontend && npm ci && npx playwright install chromium
```

## What it does

Playwright boots the stack itself — no separate setup, no servers to start by hand:

1. `scripts/e2e-backend.mjs` migrates a **throwaway** sqlite database, seeds it via
   `manage.py seed_e2e`, and serves the API on **8001**.
2. `npm run build:e2e` builds the frontend and `vite preview` serves it on **4173**.

Ports are deliberately not the dev ones (8000/5173), so a running dev server is
undisturbed. If the run reports a port already in use, something is holding 8001 or
4173 — find it, don't reuse it, or you will test a stale bundle:

```bash
netstat -ano | grep -E ":(8001|4173)\s+.*LISTENING"
taskkill //PID <pid> //F
```

## The seven checks

| Test | What it protects |
|---|---|
| renders seeded orders, groups older behind the toggle | the core dashboard read path |
| older-orders toggle reveals them | the `showOlder` interaction |
| opening the dashboard syncs exactly once | one sync per page load, not one per component |
| a failing Clover sync does not blank the dashboard | documented resilience — a Clover outage must not produce a dead screen |
| sending an SMS marks the order notified | the send flow + optimistic update |
| loads without console errors or uncaught exceptions | silent runtime breakage |
| never calls an API outside the local origin | **the suite must not be talking to production** |

## Three traps this setup exists to avoid

**1. Never let it point at production.** `vite build` defaults to `--mode production`,
which loads `.env.production` and bakes its absolute API URL into the bundle — that
once sent this entire suite, login included, at the real production API. The fix is
`--mode e2e` (see `frontend/.env.e2e`). The last test in the table above fails loudly
if that ever regresses. If you change the build wiring, keep that test.

**2. Never send a real SMS.** Twilio and Clover are intercepted at the network layer,
*and* `scripts/e2e-backend.mjs` blanks their credentials anyway. Don't remove either
layer, and don't add a test that lets a send request through.

**3. React StrictMode is why this runs against a build, not the dev server.**
StrictMode double-invokes effects in development only, so a dev-server run would fire
every mount-time request twice and make "syncs exactly once" meaningless. Also expected
in the logs: two `GET /api/orders/` per load — one renders local orders immediately,
one reloads after the sync. That is deliberate; see the comment in `src/hooks/useOrders.ts`.

## When it fails

Playwright writes a page snapshot and a trace under `frontend/test-results/`. Read the
snapshot first — it is the fastest way to see what the page actually looked like:

```bash
cat frontend/test-results/<test-name>/error-context.md
```

For step-by-step replay: `npx playwright show-trace frontend/test-results/<test-name>/trace.zip`

A failure here is a real finding, not a formality. If a test is wrong rather than the
app, fix the test and say why — do not delete the assertion.
