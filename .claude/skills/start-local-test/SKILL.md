---
name: start-local-test
description: Start Django backend, Vite frontend, and ngrok tunnel for local testing
---

Start all three local servers for testing the Chiang Mai Notification app.

**Project root:** `C:\Users\meanp\Desktop\VSCODE\chiang-mai\chiang-mai-notification`

## Steps

### 1. Start Django Backend

```bash
cd "C:/Users/meanp/Desktop/VSCODE/chiang-mai/chiang-mai-notification/backend" && \
C:/Users/meanp/Desktop/VSCODE/chiang-mai/chiang-mai-notification/backend/venv/Scripts/python.exe \
manage.py runserver 0.0.0.0:8000
```

Run in background. The venv Python is at `backend/venv/Scripts/python.exe`.

### 2. Start Vite Frontend

```bash
cd "C:/Users/meanp/Desktop/VSCODE/chiang-mai/chiang-mai-notification/frontend" && \
npx vite --host 0.0.0.0
```

Run in background. Listens at `http://localhost:5173`, proxies `/api/*` to Django at `:8000`.

### 3. Start ngrok Tunnel

```bash
ngrok http 8000 --log=stdout
```

Run in background. The tunnel URL (e.g. `https://xxxx.ngrok-free.dev`) will appear in the output.

### 4. (Optional) Watch SMS Activity

To monitor SMS sending in real time, use Monitor on the backend task output file with:

```
tail -f <backend-log-file> | grep --line-buffered -i "sms\|twilio\|error\|sent"
```

## Verification

- **Backend:** `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/orders/` should return `200`
- **Frontend:** `curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/` should return `200`
- **ngrok:** Look for `started tunnel ... url=` in the ngrok task output

## Testing SMS

To send an SMS to a pending order:

```bash
curl -s -X POST http://127.0.0.1:8000/api/orders/<id>/send/ \
  -H "Content-Type: application/json"
```

Find pending orders: `GET http://127.0.0.1:8000/api/orders/?status=pending`

## Cleanup

Stop the three background tasks when done to free ports 8000, 5173, and 4040.
