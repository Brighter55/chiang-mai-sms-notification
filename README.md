# Chiang Mai Notification

SMS notification system for Clover POS — reminds customers their online orders are ready for pickup.

## How it works
```
Customer places order on the Clover Online Ordering Storefront
  ▼
Dashboard "Refresh" button → POST /api/orders/sync/
  ├── 1. GET /v3/merchants/{mId}/orders?filter=modifiedTime>=…  → recent orders
  ├── 2. For each new/pending order:
  │     GET /v3/merchants/{mId}/orders/{orderId}?expand=lineItems,orderType
  │     → gets items summary + order type + customer ID
  ├── 3. GET /v3/merchants/{mId}/customers/{customerId}?expand=phoneNumbers
  │     → gets customer name + phone number
  ├── 4. is_online_order() check → filters out Dine-In
  ├── 5. Customer has name + phone? → skips if not
  └── 6. Save to PostgreSQL → visible on dashboard
  └── 7. click "send" to send SMS via twilio to remind customer their order is ready
```

Orders are pulled with a **merchant-generated Clover API token** — no developer
app or app approval required. There is **no auto-polling**: orders are fetched
from Clover only when Refresh is clicked. Orders already sent or cancelled are
never re-fetched.

## Stack

- **Backend**: Django + Django REST Framework + SQLite (PostgreSQL-ready)
- **Frontend**: React + TypeScript + Vite + Tailwind CSS + shadcn/ui
- **SMS**: Twilio

## Quick Start

### Backend

```sh
cd backend
python -m venv venv
source venv/Scripts/activate  # or venv/bin/activate on Git Bash
pip install -r requirements.txt
cp .env.example .env          # edit .env to add your Twilio credentials
python manage.py migrate
python manage.py runserver
```

### Frontend

```sh
cd frontend
npm install
npm run dev
```

The frontend dev server proxies `/api` requests to `http://127.0.0.1:8000`.

## Switching to PostgreSQL

1. Update `.env`:
   ```
   DATABASE_URL=postgres://user:password@localhost:5432/clover_notify
   ```
2. Install the driver:
   ```sh
   pip install psycopg[binary]
   # or for psycopg2: pip install psycopg2-binary
   ```
3. Create the database:
   ```sh
   createdb clover_notify
   ```
4. Run migrations: `python manage.py migrate`

## Environment Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DATABASE_URL` | Database connection string |
| `CLOVER_API_TOKEN` | Merchant-generated Clover API token (dashboard → Account & Setup → API Tokens) |
| `CLOVER_MERCHANT_ID` | Your Clover merchant ID (e.g. `DTWTK…`) |
| `CLOVER_USE_SANDBOX` | `True` = sandbox API, `False` = production (⚠️ defaults to `True` — must set `False` in production) |
| `CLOVER_SYNC_LOOKBACK_DAYS` | How far back each manual sync looks (default `2`) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio sender phone number (E.164) |
| `MERCHANT_NAME` | Your shop name (shown in SMS) |
