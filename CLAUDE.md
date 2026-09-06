# CLAUDE.md

Guidance for Claude Code sessions on the **Chiang Mai Notification** project.

## What this is

Web app for a Chiang Mai restaurant running Clover POS. Staff open a dashboard,
click **Refresh** to manually pull recent online/pickup/delivery orders from
Clover, then click **Send** on an order to SMS the customer a "ready for pickup"
message via Twilio. The same frontend also serves public pages (Privacy / EULA /
Support) and a public SMS opt-in endpoint.

- Repo root: `.../chiang-mai-notification` — remote `origin` → `github.com/Brighter55/chiang-mai-sms-notification`
- Backend: Django 5 + Django REST Framework in `backend/`
- Frontend: React 19 + TypeScript + Vite + Tailwind (shadcn/ui-style components) in `frontend/`
- Clover REST **v3** is called with a merchant-generated API token.
- Server `TIME_ZONE` is `America/Chicago` — the restaurant is **Chiang Mai in St. Louis, not Thailand**. Datetimes are stored as UTC.

## Layout

```
backend/
  config/        settings.py, urls.py, wsgi.py
  orders/        Order + NotificationLog models, DRF viewsets, Clover/Twilio services
  subscribers/   OptInSubscriber model (SMS opt-in) → routed to the "landing" DB
  .env.example   source of truth for local env vars
frontend/
  src/pages/     Dashboard, LoginPage, EulaPage, PrivacyPage, SupportPage
  src/lib/api.ts fetch wrapper + CSRF handling + typed API calls
  src/hooks/useOrders.ts   dashboard data hook (refresh → sync then load)
  src/components/OrderCard.tsx, ui/*
```

## Databases (two, via a router)

- **`default`** — everything from the `orders` app, plus Django auth/admin/sessions. Prod = Postgres `clover_notify`.
- **`landing`** — only the `subscribers` app (`OptInSubscriber`). Prod = Postgres `clover_landing`.
  Routed by `subscribers/router.py` (`SubscriberRouter`). Migrations for `subscribers` only apply to `landing`.

**Why two DBs:** `clover_notify` holds order/notification data; `clover_landing`
holds phone numbers that opt in from the public landing page (`POST /api/opt-in/`).
Both are **two databases on the same single Postgres server** — a deliberate
cost choice so only one database server needs to be provisioned. Don't merge
them into one.

Both default to local Postgres URLs in `settings.py` if unset, but `.env.example` sets the default DB
to SQLite for zero-setup dev. **For local dev you must also set `LANDING_DATABASE_URL`** or the
subscribers migration will try to reach a local Postgres that doesn't exist.

## Run locally

Backend (Windows, Git Bash activation shown):

```bash
cd backend
source venv/Scripts/activate            # or: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                    # edit with real Clover/Twilio creds for live testing
python manage.py migrate                # default DB (orders, auth)
python manage.py migrate --database=landing   # subscribers app only
python manage.py createsuperuser        # needed — the API requires login
python manage.py runserver              # http://127.0.0.1:8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 — proxies /api → 127.0.0.1:8000
```

End-to-end test with a reachable phone number (Django + Vite + ngrok, SMS watch):
invoke the **`/start-local-test`** skill. `DEBUG=True` auto-allows ngrok hosts.

Lint/build: `npm run lint`, `npm run build` (`tsc -b && vite build` → `dist/`).

## Key flows (read before editing)

### Manual order sync — `POST /api/orders/sync/` (auth required)
Triggered only by the dashboard **Refresh** button
1. `list_recent_clover_orders()` → GET `/v3/merchants/{mId}/orders` filtered `modifiedTime>=now - CLOVER_SYNC_LOOKBACK_DAYS` (default 2), capped at 100.
2. Orders whose local status is not `pending` (already notified/cancelled) are **never re-fetched** — they're excluded up front.
3. For each candidate (`SYNC_ORDER_CAP = 50` in `views.py`): `fetch_clover_order()` GETs the order with `expand=lineItems,orderType,orderCart.orderType`, then enriches each customer via `/customers/{cId}?expand=phoneNumbers`.
4. `is_online_order()` drops Dine-In (keeps order types containing online / pickup / pick-up / delivery — top-level and `orderCart.orderType`).
5. `extract_customer_info()`: skips if there's no customer name or no phone. Phone is normalized to E.164 (`phonenumbers`, `DEFAULT_PHONE_REGION` default `US`).
6. `extract_items_summary()` builds `"Name x2, Other"` (first 5 items).
7. `Order.update_or_create()` by `clover_order_id`. Returns `{created, updated, skipped, errors}`.

### Send SMS — `POST /api/orders/{id}/send/` (auth required)
- 409 if already notified, 400 if no customer phone.
- `send_order_notification()` in `orders/services.py` writes a `NotificationLog` (optimistic `sent`), sends via the Twilio client, on success flips `Order.status` → `notified` + stamps `notified_at`; on `TwilioRestException`/other marks the log `failed` with `error_message`.
- Message body (`build_sms_message`) is generic: no customer name, no items. Ends with `Reply STOP to opt out.`
- Response 200 on sent / 502 on failed, body = the `NotificationLog`.

### Opt-in — `POST /api/opt-in/` (public, → landing DB)
`OptInCreateView` validates + normalizes the phone with `phonenumbers`, enforces uniqueness **after** normalization (the DRF `UniqueValidator` runs on the raw input), then stores on the `landing` DB via the router.

### Session auth + CSRF (cross-origin SPA)
- Django session login: `POST /api/login/`, `POST /api/logout/`, `GET /api/me/` (in `orders/views.py`). Default DRF permission is `IsAuthenticated`.
- Sliding session cookie, 8h inactivity. `SameSite=Lax` by default.
- Prod API is on a **different origin** (`api.…`) from the dashboard, so the `csrftoken` cookie is not readable by the SPA. `login`/`me` therefore return `csrf_token` **in the JSON body**; `frontend/src/lib/api.ts` caches it and sends it as `X-CSRFToken` on unsafe methods. Don't "fix" this into a cookie-only scheme.
- Frontend routes: `/privacy`, `/eula`, `/support` are public; everything else requires auth (`AuthenticatedApp` in `App.tsx`). A global 401 handler bounces to the login page.

## Environment & secrets

- `backend/.env.example` is the documented, committed reference for every variable (see table in the README).
- Real credentials live in **gitignored** `backend/.env` (local) and `backend/.env.production` + `frontend/.env.production` (deploy). `git ls-files` confirms only `.env.example` is tracked — keep it that way.
- Frontend API base: `VITE_API_URL` (default `/api`, proxied in dev).
- `CLOVER_USE_SANDBOX` defaults `True` → `apisandbox.dev.clover.com`. Must be `False` for production.

## Skills & project settings

- `/start-local-test` — start Django + Vite + ngrok and watch for SMS activity.
- `.claude/settings.local.json` allows `WebSearch` and `WebFetch(domain:docs.clover.com)`.
- Design/UI work happens against Stitch (MCP) design-system prototypes — e.g. the warm-dark dashboard redesign.
