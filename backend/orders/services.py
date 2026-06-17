import hashlib
import hmac
import logging

import requests
from django.conf import settings
from django.utils import timezone
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from .models import NotificationLog, Order

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clover API client
# ---------------------------------------------------------------------------


def fetch_clover_order(merchant_id: str, order_id: str) -> dict | None:
    """Fetch a full Clover order by ID via the REST API.

    Requires ``CLOVER_API_TOKEN`` and ``CLOVER_MERCHANT_ID`` to be configured
    in Django settings.  Uses the sandbox or production base URL depending on
    ``CLOVER_USE_SANDBOX``.

    Returns the parsed JSON order object, or ``None`` on any failure (auth,
    network, not-found, etc.).
    """
    token = settings.CLOVER_API_TOKEN
    if not merchant_id or not token:
        logger.error("CLOVER_MERCHANT_ID and CLOVER_API_TOKEN must be configured")
        return None

    url = f"{settings.CLOVER_API_BASE_URL}/{merchant_id}/orders/{order_id}"
    params = {"expand": "lineItems,customers,orderType,orderCart.orderType"}
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "chiang-mai-notification/1.0",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        logger.error("Timeout fetching Clover order %s", order_id)
    except requests.HTTPError as exc:
        logger.error(
            "Clover API error for order %s: %s — %s",
            order_id,
            resp.status_code,
            resp.text[:500],
        )
    except requests.RequestException as exc:
        logger.error("Failed to fetch Clover order %s: %s", order_id, exc)
    return None


def is_online_order(order_data: dict) -> bool:
    """Return ``True`` if the Clover order is an online/pickup/delivery order.

    We look at ``orderType`` (in ``orderCart`` or top-level) — online ordering
    types always include customer contact info.
    """
    # Check inside orderCart first (where atomic orders put it)
    order_cart = order_data.get("orderCart", {}) or {}
    order_type = order_cart.get("orderType", {}) or {}
    type_name = (order_type.get("name") or "").lower()

    # Fall back to top-level orderType
    if not type_name:
        order_type = order_data.get("orderType", {}) or {}
        type_name = (order_type.get("name") or "").lower()

    return type_name in ("online", "pickup", "pick-up", "delivery", "online order")


def extract_customer_info(order_data: dict) -> tuple[str, str]:
    """Extract ``(name, phone)`` from a Clover order.

    Returns ``("", "")`` if no customer data is present.
    """
    customers = order_data.get("customers") or []
    if not customers:
        return "", ""

    customer = customers[0]
    first = (customer.get("firstName") or "").strip()
    last = (customer.get("lastName") or "").strip()
    name = f"{first} {last}".strip()
    # Fall back to other name fields if firstName/lastName are empty
    if not name:
        name = (customer.get("displayName") or "").strip()

    phone = ""
    phones = customer.get("phoneNumbers") or []
    if phones:
        phone = (phones[0].get("phoneNumber") or "").strip()

    return name, phone


def extract_items_summary(order_data: dict) -> str:
    """Build a human-readable summary string from the order's line items."""
    line_items = order_data.get("lineItems") or []
    if not line_items:
        return (order_data.get("title") or "").strip()

    parts = []
    for item in line_items:
        name = (
            item.get("name")
            or (item.get("item") or {}).get("name")
            or ""
        ).strip()
        qty = item.get("quantity") or item.get("quantitySold") or 1
        if name:
            parts.append(f"{name} x{qty}" if qty > 1 else name)

    summary = ", ".join(parts[:5])
    if len(parts) > 5:
        summary += f" (+{len(parts) - 5} more)"
    return summary


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

def verify_clover_signature(payload: bytes, signature_header: str) -> bool:
    """Validate the X-Clover-Signature header against the raw request body.

    Clover signs webhooks with HMAC-SHA256 using your webhook secret as the
    key.  Returns True when the signature matches (or when no secret is
    configured, for development convenience).
    """
    secret = settings.CLOVER_WEBHOOK_SECRET
    if not secret:
        logger.warning("CLOVER_WEBHOOK_SECRET is not set — skipping verification")
        return True

    expected = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# SMS sending
# ---------------------------------------------------------------------------

def build_sms_message(order: Order) -> str:
    merchant = settings.MERCHANT_NAME
    return (
        f"Hi {order.customer_name}, "
        f"your order from {merchant} is ready for pickup! 🛍️\n\n"
        f"Order: {order.items_summary or '#' + order.clover_order_id[-8:]}\n\n"
        f"Thank you!"
    )


def send_order_notification(order: Order) -> NotificationLog:
    """Send an SMS notification for *order* via Twilio.

    Creates a ``NotificationLog`` record capturing the result (sent / failed).
    On success the order's ``status`` is advanced to *notified* and
    ``notified_at`` is stamped.
    """
    message_body = build_sms_message(order)

    notification = NotificationLog.objects.create(
        order=order,
        recipient_phone=order.customer_phone,
        message_body=message_body,
        status=NotificationLog.Status.SENT,  # optimistic — updated on failure
    )

    try:
        client = Client(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN,
        )
        msg = client.messages.create(
            body=message_body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=order.customer_phone,
        )
        notification.twilio_sid = msg.sid
        notification.status = NotificationLog.Status.SENT
        notification.save(update_fields=["twilio_sid", "status"])

        order.status = Order.Status.NOTIFIED
        order.notified_at = timezone.now()
        order.save(update_fields=["status", "notified_at"])

        logger.info("SMS sent to %s (SID: %s)", order.customer_phone, msg.sid)

    except TwilioRestException as exc:
        notification.status = NotificationLog.Status.FAILED
        notification.error_message = str(exc)
        notification.save(update_fields=["status", "error_message"])
        logger.error("Twilio error for order %s: %s", order.clover_order_id, exc)

    except Exception:
        notification.status = NotificationLog.Status.FAILED
        notification.error_message = "Unexpected error sending SMS"
        notification.save(update_fields=["status", "error_message"])
        logger.exception("Unexpected error sending SMS for order %s", order.clover_order_id)

    return notification
