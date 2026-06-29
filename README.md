# Chiang Mai Notification

SMS notification system for Clover POS — reminds customers their online orders are ready for pickup.

## How it works
```
Close Online Ordering Storefront
  │ Customer places order
  ▼
Clover Backend
  │ POST webhook to registered URL
  │ Payload: {"merchants": {"{mId}": [{"objectId": "O:{UUID}", "type": "CREATE"}]}}
  ▼
POST https://your-domain.com/api/webhook/clover/
  │
  ├── 1. Parse objectId → strip "O:" prefix → get order UUID
  ├── 2. GET /v3/merchants/{mId}/orders/{orderId}?expand=lineItems,orderType
  │     → gets items summary + order type + customer ID
  ├── 3. GET /v3/merchants/{mId}/customers/{customerId}?expand=phoneNumbers  
  │     → gets customer name + phone number
  ├── 4. is_online_order() check → filters out Dine-In
  ├── 5. Customer has name + phone? → skips if not
  └── 6. Save to PostgreSQL → visible on dashboard
  └── 7. click "send" to send SMS via twilio to remind customer their order is ready
```

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
| `CLOVER_WEBHOOK_SECRET` | Clover webhook verifier token (blank = skip verification in dev) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio sender phone number (E.164) |
| `MERCHANT_NAME` | Your shop name (shown in SMS) |
