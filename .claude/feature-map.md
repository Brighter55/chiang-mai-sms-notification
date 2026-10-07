# Feature map

Read this before hunting through the tree. It maps **symptoms to files**, and — more
usefully — records the traps this codebase has already fallen into, including the fix
that *looks* right and is wrong.

Written for the case where someone hands you a vague report ("an order is missing from
the dashboard") and you need to find the code fast without flailing.

---

## Symptom → files

| Symptom | Start here |
|---|---|
| Order missing from the dashboard | Two independent causes: the sync chain (`orders/views.py:_orders_to_sync`, `services.py:is_online_order`, `attach_customer_data`) — and the list's ordering (trap 8) |
| **No** orders load — every fetch returns 500 | The deployed database is behind the code (trap 14). Check `showmigrations` before touching a query |
| Refresh is slow, or orders vanish in bulk | The 2-call invariant — `orders/views.py:_run_sync`, `services.py:fetch_customer_map` |
| "Send" button fails / 409 / 400 | `orders/views.py:OrderViewSet.send` (L211), `services.py:send_order_notification` (L346) |
| "Send Review" missing, or the dialog never warns about a repeat | `orders/views.py:OrderViewSet.review` + `review_last_sent_at` in `get_queryset`; `frontend/src/components/OrderCard.tsx` |
| A customer reported as already reviewed who was never texted | The `sent()` predicate — `orders/models.py:ReviewRequestQuerySet` |
| SMS arrives but the order stays "pending" | `services.py:send_order_notification` L374-391 |
| Login fails, or 403 on every write | The in-body CSRF scheme — `orders/views.py:LoginView` (L250), `frontend/src/lib/api.ts` |
| Works locally, 403 in production | `CORS_ALLOWED_ORIGINS` vs `CSRF_TRUSTED_ORIGINS` — `config/settings.py` L93-126 |
| Timestamps look wrong by hours | `TIME_ZONE` — see the trap below |
| Opt-in endpoint rejects a valid number | `subscribers/serializers.py:validate_phone` (L21) |
| Dashboard renders but never updates | `frontend/src/hooks/useOrders.ts` |
| Dashboard never refreshes on its own, or refreshes too often | The two auto-refresh timers — `hooks/useOrders.ts` (`runRefresh` modes) and `hooks/useIntervalSettings.ts` (1–60 min, per-browser) |
| Orders render, SMS button misbehaves | `frontend/src/components/OrderCard.tsx` |
| Nothing on the page is clickable until a reload, after closing a dialog | Trap 13 — the `modal` prop on the menu that opened it |

---

## Where the code lives

```
backend/
  config/settings.py     env vars, DRF config, CORS/CSRF, DB router wiring
  orders/views.py        DRF viewsets + the sync orchestration (_run_sync)
  orders/services.py     all Clover + Twilio I/O and every parser
  subscribers/           opt-in model -> routed to the "landing" DB
frontend/src/
  lib/api.ts             fetch wrapper, CSRF cache, every API call
  hooks/useOrders.ts     dashboard data: mount load, manual refresh, the two
                         auto-refresh timers, optimistic SMS
  hooks/useIntervalSettings.ts  auto-refresh cadences, clamped 1-60 min, localStorage
  pages/Dashboard.tsx    today/older grouping, empty + error states, settings toggle
  components/OrderCard.tsx
```

The backend split that matters: **`views.py` orchestrates, `services.py` does I/O and
parsing.** Pure parsers in `services.py` are where the subtle bugs live and where the
tests are.

---

## Traps

Each of these has already bitten this codebase. The "wrong fix" column exists because
several of them look like obvious cleanups.

### 1. Clover customers arrive as bare references

`GET /orders?expand=customers` returns customers as `{id, href}` — **no name, no phone.**
The name exists only on the customer record.

- **Wrong fix:** copy `phoneNumbers` across and move on. An earlier version did exactly
  that, so `extract_customer_info` saw no name, every order was skipped as "no customer",
  and orders silently vanished from the dashboard.
- **Right fix:** merge the *whole* record — `services.py:attach_customer_data` (L191).
- **Related:** test fixtures must use bare `{id, href}` refs. A fixture with a name baked
  in **hides this exact bug** — see `orders/tests.py:26-30`, which says so explicitly.

### 2. Two Clover requests per sync, no matter how many orders

- **Wrong fix:** fetch each order, then each customer, individually. That version took
  ~20s, tripped Clover's **429 rate limit**, and — because `_call_clover` returns `None`
  on failure — rate-limited orders were **silently dropped**.
- **Right fix:** keep it at exactly 2 calls (list orders with `expand`, then one paged
  customer sweep). `orders/tests.py:SyncCallCountTests` pins this; if you add a request
  per order, those tests fail. That is intentional.

### 3. A sync must never undo a notification

`_save_orders` (`views.py:80`) writes with `update_fields=["customer_name",
"customer_phone", "items_summary"]` (L100) and deliberately omits `status`/`notified_at`.

- **Wrong fix:** "simplify" the bulk update to write the whole row. That reverts notified
  orders to pending and can re-text a customer.
- Guarded by `test_sync_does_not_clobber_the_status_of_an_existing_order`.

### 4. The CSRF token comes back in the JSON body — on purpose

Production serves the API from a different origin (`api.…`) than the dashboard, so the
`csrftoken` cookie is **not readable** by the SPA. `login` (L277) and `me` (L299) return
it in the body; `frontend/src/lib/api.ts` caches it and sends `X-CSRFToken`.

- **Wrong fix:** "clean this up" into a cookie-only scheme. It will pass locally (shared
  host) and break in production. CLAUDE.md warns about this; take it seriously.
- Local dev does fall back to reading the cookie (`api.ts:18-19`) — that fallback is why
  the wrong fix *looks* like it works.

### 5. The restaurant is in St. Louis, not Thailand

`TIME_ZONE = "America/Chicago"`. The project name says "Chiang Mai" because that's the
restaurant's name. Datetimes are stored UTC.

- **Wrong fix:** change the timezone to `Asia/Bangkok`. Nothing in the code will complain
  and every timestamp will be wrong by 12 hours.
- `Dashboard.tsx:isToday` does local-day grouping, so this shows up as orders appearing
  under the wrong day.

### 6. Overlapping refreshes are rejected by a process-local lock

`views.py:39` `_sync_lock`, checked non-blocking at L192. Two staff clicking Refresh, or
React's dev-mode double-mount, must not crawl Clover twice; the duplicate gets the
all-zeros response.

- Note it is **process-local** — it does nothing across multiple gunicorn workers. Don't
  mistake it for a distributed lock.

### 7. Smaller ones, all real

| Trap | Where | The wrong fix |
|---|---|---|
| Clover lists come back as `{elements: [...]}` *or* `[]` *or* missing | `services.py:_extract_list` (L28) | `data["elements"]` directly — `KeyError` |
| A phone that won't parse falls back to `+<digits>` | `services.py:_normalize_phone` (L44) | Raising instead — breaks existing order data |
| Order-type matching normalizes case/punctuation and substring-matches `_ACCEPTED_ORDER_TYPE_KEYWORDS`, checking **both** `name` and `label` | `services.py:is_online_order` (L164) | Exact `== "Online"` — drops real orders; or reading only `name`, which misses a type Clover put in `label` |
| Clover sometimes rejects the `filter` syntax; there's a one-shot retry without it | `services.py:list_recent_clover_orders` (L248) | Removing the retry |
| There is no "fetch these customer ids" endpoint — it's a sweep with early stop, then per-id fallback | `services.py:fetch_customer_map` (L285) | Assuming one request per id |
| Uniqueness must be re-checked **after** phone normalization | `subscribers/serializers.py:43` | Trusting DRF's `UniqueValidator` — it runs on raw input |
| `landing` is a separate DB by design | `subscribers/router.py` | Merging the two DBs to "simplify" |
| `CLOVER_USE_SANDBOX` defaults `True` | `config/settings.py` | Forgetting to set `False` in prod |
| DELETE on `/api/orders/{id}/` **works** while POST/PUT/PATCH are no-ops (read-only serializers) | `orders/views.py:OrderViewSet` | Assuming the whole viewset is read-only |

### 8. Listing orders silently loses its ordering

`Order.Meta.ordering = ["-created_at"]` is dropped the moment a queryset is annotated
with an aggregate. `OrderViewSet.get_queryset` annotates `notification_count` for the
list action, so the emitted SQL had **no `ORDER BY` at all** — and returned oldest-first.

- **Wrong fix:** trusting `Meta.ordering` and assuming the list is newest-first.
- **Right fix:** `.order_by("-created_at")` explicitly, after the annotate
  (`views.py:get_queryset`).
- **Why it matters:** DRF paginates this endpoint (page size 50) and the dashboard reads
  **only page 1**. Unordered, page 1 is not guaranteed to hold the newest orders — which
  is the "order missing from the dashboard" symptom again, arriving from a completely
  different direction than trap #1.
- Guarded by `OrderListOrderingTests`, including a direct assertion on `.ordered`, since
  a behavioural test alone can pass by luck on a database that happens to return rows in
  insertion order.

### 9. Frontend: mount is not one requestOpening the dashboard fires **two** `GET /orders/` and one `POST /orders/sync/` — the
initial `loadOrders()` renders local data immediately, then `refresh()` syncs and reloads.
Under React `StrictMode` (`main.tsx:8`) dev mode doubles all of it.

- This is deliberate (first paint must never wait on Clover) — see the comment in
  `useOrders.ts`.
- **Consequence for tests:** any E2E assertion counting requests will fail in dev mode.
  Assert against a production build, or test the backend lock instead.

---

## Invariants that must not regress

1. A sync costs **2** Clover requests regardless of order count.
2. A sync **never** changes `status` or `notified_at`.
3. Customers are merged as **whole records**, from `{id, href}` references.
4. Phones reach the DB as **E.164**.
5. The dashboard's first paint **never waits** on Clover.
6. A `NotificationLog` is written for **every** send attempt, success or failure — it is
   the audit trail.
7. A **failed** send leaves the order `pending`. Only a confirmed success flips it to
   `notified`. If a failure ever marked it notified, staff would stop chasing a customer
   who was never actually told.
8. The SMS body stays generic — **no customer name, no item list** (privacy: the message
   lands on lock screens). Both templates, not just the pickup one. The *dialog* naming
   the customer is fine; that never leaves staff's screen.
9. A review send **never** touches `Order.status` or `notified_at`. A review ask and a
   pickup notice are different facts about a customer, and letting one imply the other
   would hide an order nobody has chased.
10. **Every** send attempt is audited — `NotificationLog` for pickup messages,
    `ReviewRequest` for review messages. A review counts as sent only with a `twilio_sid`,
    because the row is written before Twilio is called and a crash mid-send must not look
    like a delivered message.

Invariants 1–10 are all pinned by `orders/tests.py`. Breaking one should turn the suite red.

### 10. A second annotation can silently rewrite the GROUP BY

`OrderViewSet.get_queryset` annotates the list with `Count("notifications")` and, for review
state, a `Subquery`.

- **Wrong fix:** wrap the review subquery in `Coalesce(...)` — the obvious way to turn a
  NULL into `0` for the frontend. `Func.get_group_by_cols()` makes Django append the whole
  expression to the `GROUP BY` clause (`GROUP BY …, 11`), so the query groups by a
  per-row subquery. It works on SQLite, which is what `check.py` and CI run, and is then
  never exercised against Postgres, which is what production runs.
- **Also wrong:** a second join-backed `Count(...)`. Two joins through one `annotate` is a
  Cartesian product, so `notification_count` doubles the moment any review row exists.
- **Right fix:** a **bare** correlated `Subquery`, no `Func` wrapper, and no count field at
  all — `review_last_sent_at` answers the question on its own.
  `OrderReviewStateTests.test_review_rows_do_not_inflate_the_notification_count` is the guard.
- **Not the whole story:** when the dashboard 500s on *every* order fetch, this trap is the
  obvious suspect — and it has been the wrong one. Check the deployed schema first: trap 14.

### 11. A review row is written before Twilio is called

`send_review_request` inserts the row as `sent` optimistically, so a crash still leaves an
audit trail — the same shape as the pickup path.

- **Wrong fix:** treat `status=sent` as "this customer was asked". A process that dies
  between the INSERT and `messages.create` leaves exactly that, for a text that never went
  out, and staff would be warned off re-asking forever.
- **Right fix:** `ReviewRequest.objects.sent()` — `status=sent` **and** a non-null
  `twilio_sid` — used by both the view and the tests so they cannot drift.

### 12. The sends retire in-flight polls; the poll guard alone does not

`runRefresh` refuses to *start* a poll while a send is in flight, but a `GET /api/orders/`
already on the wire still resolves afterwards.

- **Wrong fix:** rely on the `sendingIdRef` guard alone. `loadOrders` only discards a
  response when a newer load has begun, and none can begin during a send — so the stale
  response lands last and reverts the optimistic update.
- **Right fix:** both `sendSms` and `sendReview` bump `latestLoadRef` as they start, which
  is what retires the in-flight response.

### 13. A modal dialog opened from a modal menu freezes the whole page

Reported as *"clicking Cancel in the Send Review dialog leaves nothing clickable"*. The
Cancel button is innocent — the damage is done when the dialog **opens**.

`@radix-ui/react-dismissable-layer` saves and restores `document.body.style.pointerEvents`
with **no stack**:

```js
originalBodyPointerEvents = ownerDocument.body.style.pointerEvents;
ownerDocument.body.style.pointerEvents = "none";
// on cleanup:
ownerDocument.body.style.pointerEvents = originalBodyPointerEvents;
```

`DropdownMenu` defaults to `modal`, and both the modal menu and the AlertDialog use that
layer with outside pointer events disabled while open. So:

1. The menu opens → body becomes `"none"`.
2. **Send Review** mounts the dialog while the menu is still mounted (Radix's `Presence`
   unmounts it a commit later) → the dialog captures `"none"` as its baseline.
3. The menu unmounts and restores `""`.
4. The dialog closes and restores the value from step 2: **`"none"`**.

`pointer-events` is inherited, so `none` on `<body>` disables every button, link and menu
on the page, permanently, until a reload. It bites the confirm path exactly as hard as
Cancel — Cancel is just where someone noticed.

- **Wrong fix:** defer the dialog open with `setTimeout`/`requestAnimationFrame` so the menu
  unmounts first. It papers over the ordering, is timing-dependent, and leaves the trap
  armed for the next dialog.
- **Right fix:** `<DropdownMenu modal={false}>`. The menu then never touches the body value,
  so the dialog's save/restore is symmetric. A one-item action menu has no reason to freeze
  the rest of the dashboard anyway.
- **General rule:** never open a modal dialog from a modal dropdown/popover without
  `modal={false}` on the menu. Any two overlapping Radix layers can corrupt this value.
- Guarded by `review.spec.ts` — *"cancelling/sending a review leaves the page usable"*,
  which asserts `<body>` is not left at `pointer-events: none` **and** that a click on the
  dashboard still works.

### 14. A database behind the code 500s the whole dashboard

Reported as *"the google review update ... unable to fetch the order, returns 500"* — in
production, right after the review feature shipped.

`OrderViewSet.get_queryset` annotates the order list with a correlated `Subquery` over
`ReviewRequest` (trap 10), so **every** `GET /api/orders/` references
`orders_reviewrequest`, even with zero review rows. On a deployed database where
`0002_reviewrequest` was never applied, that is `ProgrammingError: relation
"orders_reviewrequest" does not exist` on every order fetch. Not a broken review button — a
dashboard with no orders on it.

- **Wrong fix:** treat it as a query bug and start editing `get_queryset`. That is the shape
  trap 10 describes, it is where this symptom points, and it is where the hunt went first.
  The query is fine: run against Postgres 17 with the real synced orders, it returns rows.
  **A 500 with no explicit status code is a database fault, not a query one** — every other
  branch of the order routes returns a deliberate 4xx/5xx.
- **Right fix, and the first thing to run:** `python manage.py showmigrations orders` against
  the *deployed* database. A migration file in the repo says nothing about a database.
- **Why no gate caught it:** `makemigrations --check` (a `check.py` gate) proves the file
  exists, never that a database has run it. Nothing in the repo can see the deployed
  schema.
- **Durable fix:** `scripts/release.sh`, run as a pre-deploy step, migrates **both**
  databases and fails the deploy if it cannot. The deploy config lives in the DigitalOcean
  console rather than this repo, so no local check can confirm it is still wired up.
- **Why it hurt more than it should have:** the review table sits on the *order list's*
  critical path, so the blast radius of any schema lag is the entire dashboard rather than
  the one feature that changed. Worth asking, for any new state, whether the list really
  needs it.

---

## Where the tests won't save you

`scripts/check.py` is the gate. `orders/tests.py` covers the **sync path** and the
**SMS path** (message shape, every send outcome, the endpoint's 409/400/200/502 mapping).
Uncovered, in rough order of risk:

- **Whether a deployed database has the migrations applied.** No gate can see it, and it
  took the dashboard down once — trap 14. `scripts/release.sh` is the only thing standing
  between a schema change and a repeat, and it lives in the DigitalOcean console where
  nothing local can check it.
- **`subscribers/`** — no tests at all, including the normalize-then-check-uniqueness
  logic that has its own trap (above).
- **Auth views** (`LoginView`, `LogoutView`, `MeView`) and permission enforcement.
- **The frontend's pure logic** — there are no frontend unit tests. The Playwright suite
  covers the dashboard end to end (see `/verify-dashboard`), but helpers like `timeAgo`
  and `isToday` are only exercised indirectly through it.
- Most pure parsers: `is_online_order` edge cases, `extract_items_summary` truncation,
  `_normalize_phone` failure paths, `list_recent_clover_orders` retry.

---

## API routes

| Method | Path | Auth |
|---|---|---|
| POST | `/api/login/` | public → returns `csrf_token` |
| POST | `/api/logout/` | public |
| GET | `/api/me/` | session |
| GET | `/api/orders/` | session (`?status=` optional) |
| GET/DELETE | `/api/orders/{id}/` | session |
| POST | `/api/orders/sync/` | session |
| POST | `/api/orders/{id}/send/` | session |
| POST | `/api/orders/{id}/review/` | session |
| GET | `/api/logs/` | session |
| POST | `/api/opt-in/` | **public** → landing DB |
| — | `/admin/` | staff |

Default DRF permission is `IsAuthenticated` (`config/settings.py:135-140`).

---

## Verifying a change

```bash
python scripts/check.py           # the fast gates; CI runs exactly this
python scripts/check.py --e2e     # ...plus the browser suite
```

For anything touching the dashboard, drive the real UI rather than reasoning about it
from the source — see the `/verify-dashboard` skill.
