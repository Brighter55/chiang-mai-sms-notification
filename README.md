# Chiang Mai Notification

SMS notification system for Clover POS — reminds customers their online orders are ready for pickup.

## How it works

1. Clover POS fires a webhook when an order is placed → stored in the database
2. Open the dashboard → see all pending orders
3. When an order is physically ready, click **Send SMS** → Twilio texts the customer

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

### Test the webhook

```sh
curl -X POST http://127.0.0.1:8000/api/webhook/clover/ \
  -H "Content-Type: application/json" \
  -d '{"payload": {"id": "ORDER-001", "customer": {"name": "Jane", "phoneNumber": "+15551234567"}, "lineItems": [{"name": "Coffee"}], "title": "Test"}}'
```

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
