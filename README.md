# Chiang Mai Notification

SMS notification dashboard for **Chiang Mai** (a St. Louis restaurant on Clover POS) — pulls online orders from Clover and lets staff send customers an SMS telling them their order is ready for pickup.

Password-protected dashboard, live order cards, one-click SMS via Twilio. No developer app or app approval required — it uses a **merchant-generated Clover API token**.

## Impacts

**Before this tool:** whenever an online order was ready for pickup, a staff member had to pull up the customer in Clover, read the phone number off the screen, key it into the restaurant phone, and hand-type a text.

**With the dashboard, the customer's number never has to be typed.**

- **No manual number entry** — the phone number is pulled straight from the Clover order (auto-normalized to E.164), so sending a pickup reminder is never a matter of copying digits into a phone.
- **Faster at rush** — a ready-for-pickup text is now one click on an order card instead of a lookup → typing → send SMS. Staff have more time doing other things else
- **Fewer mistakes** — no transposed digits, wrong area codes, or typos from reading a screen and re-typing it. That means fewer texts sent to the wrong person and fewer ready orders left sitting because a number was entered wrong.
- **Consistent every time** — every customer gets the same clear "ready for pickup" message (with the Twilio opt-out line), no matter who is on shift or how rushed things get.
- **Built-in record** — each send is logged with a sent/failed status, so the restaurant can see when a customer was notified instead of relying on memory.

## Features

- 🔐 Session-based login (Django auth) — the dashboard is private
- 🔄 **Manual** Clover order sync — pull recent online orders with one click (no background polling)
- 📲 Send "ready for pickup" SMS to a customer with one click (Twilio)
- 📋 Today's orders up top, older orders collapsed behind a toggle
- 🧾 Per-order notification history (sent / failed logs)
- 📝 Public pages: Privacy Policy, EULA, Support — plus an SMS opt-in endpoint

## How it works

```
Staff clicks "Refresh" in the dashboard
  ▼
POST /api/orders/sync/
  1. GET /v3/merchants/{mId}/orders?filter=modifiedTime>=…
       &expand=lineItems,orderType,orderCart.orderType,customers
       → recent orders (default: last 2 days), with everything the sync needs
  2. Skip any order already notified or cancelled locally
  3. Drop Dine-In orders — only online / pickup / delivery order types are kept
  4. Drop orders with no customer name or no phone number
  5. GET /v3/merchants/{mId}/customers?expand=phoneNumbers
       → ONE paged sweep for every customer on the batch. The order endpoint
         returns customers as bare {id} references with no name or phone.
  6. Summarize line items ("Pad Thai x2, …") → save/update in PostgreSQL
  ▼
Staff clicks "Send" on an order card
  ▼
POST /api/orders/{id}/send/  →  Twilio SMS  →  order status: pending → notified
```

Orders are pulled with a **merchant-generated Clover API token**
from Clover only when Refresh is clicked. Orders already sent or cancelled are
never re-fetched.

**The whole sync is exactly two Clover requests**, however many orders come back.
That is a hard constraint, not an accident: fetching orders or customers
individually took ~20s and tripped Clover's 429 rate limit, and because a failed
call returns `None`, rate-limited orders were silently dropped. Tests pin it.

The SMS message is generic (no customer name, no item list), e.g.:

```
Your order from Chiang Mai is ready for pickup! 🛍️

Thank you!

Reply STOP to opt out.
```

## Stack

| Layer | Tech |
|---|---|
| Backend | Django + Django REST Framework |
| Databases | PostgreSQL (`clover_notify` default) + second DB `clover_landing` for the opt-in app, dev falls back to SQLite |
| Frontend | React + TypeScript + Vite + Tailwind CSS (shadcn/ui-style components) |
| SMS | Twilio |
| Phone validation | `phonenumbers` (E.164) |

## Repo layout

```
backend/
  config/          Django settings, URL routing
  orders/          Order + NotificationLog models, DRF viewsets, Clover/Twilio services
  subscribers/     OptInSubscriber model → stored on the separate "landing" DB
  .env.example     documented env vars (committed)
frontend/
  src/pages/       Dashboard, LoginPage, EulaPage, PrivacyPage, SupportPage
  src/lib/api.ts   API client + CSRF handling
  src/hooks/       useOrders (sync-then-load, optimistic SMS state)
```

## API overview

All endpoints return JSON. Everything except `/api/login/`, `/api/logout/` and `/api/opt-in/` requires a session.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/login/` | Log in (username + password), returns `csrf_token` |
| POST | `/api/logout/` | End the session |
| GET | `/api/me/` | Current user + `csrf_token` |
| GET | `/api/orders/` | List orders (`?status=pending` optional) |
| GET | `/api/orders/{id}/` | Order detail incl. notification history |
| POST | `/api/orders/sync/` | Manual Clover sync → `{created, updated, skipped, errors}` |
| POST | `/api/orders/{id}/send/` | Send the SMS reminder (marks order notified) |
| GET | `/api/logs/` | Notification send history |
| POST | `/api/opt-in/` | Public: store a phone number with SMS consent (landing DB) |
| — | `/admin/` | Django admin for orders & notification logs |

Auth is **session-based** with sliding 8h expiry. Because the production API
lives on a different origin from the dashboard, the CSRF token is returned in the
`login`/`me` JSON body and sent back as an `X-CSRFToken` header by the frontend.

## Quick Start

### Backend

```sh
cd backend
python -m venv venv
source venv/Scripts/activate        # or: venv\Scripts\activate (PowerShell / venv/bin/activate on Git Bash)
pip install -r requirements.txt
cp .env.example .env                # add Clover + Twilio credentials to go live
python manage.py migrate            # main database (orders, auth)
python manage.py migrate --database=landing   # opt-in app → separate "landing" DB
python manage.py createsuperuser    # the dashboard requires a login
python manage.py runserver
```

> **Two databases:** the `subscribers` app is routed to a second database named
> `landing`. For local dev, add `LANDING_DATABASE_URL=sqlite:///landing.sqlite3`
> to `.env` — otherwise the landing migration will try to reach a local Postgres.
> Prod uses PostgreSQL for both (see `.env.production`).
>
> `clover_notify` stores orders/notifications; `clover_landing` stores the
> phone numbers that opt in from the landing page. They're two databases on the
> **same** Postgres server — a deliberate choice so only one database server has
> to be provisioned.

### Frontend

```sh
cd frontend
npm install
npm run dev
```

The frontend dev server proxies `/api` requests to `http://127.0.0.1:8000`.

### Testing end-to-end with real SMS

There's a project skill that starts Django + Vite + an ngrok tunnel and watches
the backend log for SMS activity — run **`/start-local-test`**. `DEBUG=True`
auto-allows ngrok hosts so session cookies work over the tunnel.

### Automated checks

```sh
python scripts/check.py           # Django check, migrations, backend tests,
                                  # ruff, frontend lint + build
python scripts/check.py --e2e     # ...plus the Playwright dashboard suite
```

CI runs exactly this script, so a green local run means a green build. The E2E
suite drives the real dashboard in a browser — logging in, rendering orders,
refreshing, sending an SMS — against a throwaway database, with Clover and Twilio
both intercepted so nothing leaves the machine. See the `/verify-dashboard` skill.
First run needs `npx playwright install chromium`.

## Switching to PostgreSQL

1. Update `.env`:
   ```
   DATABASE_URL=postgres://user:password@localhost:5432/clover_notify
   LANDING_DATABASE_URL=postgres://user:password@localhost:5432/clover_landing
   ```
2. Create both databases:
   ```sh
   createdb clover_notify
   createdb clover_landing
   ```
3. Run migrations: `python manage.py migrate` and `python manage.py migrate --database=landing`

`psycopg2-binary` is already in `requirements.txt`.

## Environment Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True`/`False` (defaults `True`; also auto-allows ngrok hosts) |
| `ALLOWED_HOSTS` | Comma-separated hosts (defaults `localhost,127.0.0.1`) |
| `DATABASE_URL` | Main DB (orders/auth). Defaults to SQLite in `.env.example` |
| `LANDING_DATABASE_URL` | Second DB for the opt-in subscribers app |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins allowed to call the API |
| `CSRF_TRUSTED_ORIGINS` | Must include every CORS origin above for cross-domain session auth |
| `CLOVER_API_TOKEN` | Merchant-generated Clover API token (dashboard → Account & Setup → API Tokens) |
| `CLOVER_MERCHANT_ID` | Your Clover merchant ID (e.g. `DTWTK…`) |
| `CLOVER_USE_SANDBOX` | `True` = sandbox API, `False` = production (⚠️ defaults `True` — set `False` in prod) |
| `CLOVER_SYNC_LOOKBACK_DAYS` | How far back each manual sync looks (default `2`) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio sender number (E.164) |
| `DEFAULT_PHONE_REGION` | Region used to parse/normalize phones (default `US`) |
| `MERCHANT_NAME` | Shop name shown in the SMS |
| `VITE_API_URL` *(frontend)* | Production API base; defaults to `/api` (proxied in dev) |

## Deployment notes

- Production config lives in gitignored `backend/.env.production` and `frontend/.env.production` (frontend points `VITE_API_URL` at the API host, e.g. `https://api.chiangmaistl-infra.com/api`).
- Run the Django backend with **gunicorn** (`gunicorn config.wsgi`) and serve the built frontend (`npm run build` → `dist/`) as static files.
- Set `DEBUG=False`, `CLOVER_USE_SANDBOX=False`, and real `ALLOWED_HOSTS` in production.
- Keep real credentials out of git — only `backend/.env.example` is tracked.
