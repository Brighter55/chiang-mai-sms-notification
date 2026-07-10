import hashlib
import hmac
import logging
import re

import phonenumbers
import requests
from django.conf import settings
from django.utils import timezone
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from .models import NotificationLog, Order

logger = logging.getLogger(__name__)

_NON_DIGIT_RE = re.compile(r"[^\d]+")


# ---------------------------------------------------------------------------
# Helpers for Clover's API format
# ---------------------------------------------------------------------------


def _extract_list(data: dict, key: str) -> list:
    """Clover returns lists as ``{"elements": [...]}`` or plain ``[]``.

    This helper normalises both forms — and also handles the case where *data*
    is ``None``, the key is missing, or the value is already a list.
    """
    if not data:
        return []
    val = data.get(key)
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return val.get("elements") or []
    return []


def _normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 format (starts with ``+``).

    Uses the phonenumbers library with the project's default phone region
    (US).  Falls back to treating bare digits as a raw number if the library
    cannot parse the input, to avoid breaking existing Clover order data.
    """
    phone = phone.strip()
    if not phone:
        return ""
    if phone.startswith("+"):
        return phone

    try:
        parsed = phonenumbers.parse(phone, settings.DEFAULT_PHONE_REGION)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass

    # Fallback: strip non-digits and prepend "+"
    digits = _NON_DIGIT_RE.sub("", phone)
    return f"+{digits}" if digits else ""


# ---------------------------------------------------------------------------
# Clover API client
# ---------------------------------------------------------------------------


def _call_clover(path: str, params: dict | None = None) -> dict | None:
    """Make a GET request to the Clover REST API.

    Returns the parsed JSON response, or ``None`` on failure.
    """
    token = settings.CLOVER_API_TOKEN
    if not token:
        logger.error("CLOVER_API_TOKEN is not configured")
        return None

    url = f"{settings.CLOVER_API_BASE_URL}/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "chiang-mai-notification/1.0",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        logger.error("Timeout fetching %s", url)
    except requests.HTTPError as exc:
        logger.error(
            "Clover API error %s: %s — %s",
            url, resp.status_code, resp.text[:500],
        )
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
    return None


def fetch_clover_order(merchant_id: str, order_id: str) -> dict | None:
    """Fetch a full Clover order by ID via the REST API.

    Clover's ``expand`` parameter only partially expands related resources, so
    we also fetch customer details separately when present.

    Returns a normalised order dict with ``lineItems`` as a flat list and
    ``customers`` with full name/phone data, or ``None`` on failure.
    """
    order_data = _call_clover(
        f"{merchant_id}/orders/{order_id}",
        {"expand": "lineItems,orderType,orderCart.orderType"},
    )
    if order_data is None:
        return None

    # -- Normalise line items into a flat list ------------------------------
    raw_items = order_data.get("lineItems")
    if isinstance(raw_items, dict):
        order_data["lineItems"] = _extract_list(raw_items, "elements")

    # -- Fetch full customer details if we have IDs ------------------------
    raw_customers = order_data.get("customers")
    customer_ids = []
    if isinstance(raw_customers, dict):
        customer_ids = [
            c["id"]
            for c in _extract_list(raw_customers, "elements")
            if c.get("id")
        ]
    elif isinstance(raw_customers, list):
        customer_ids = [c["id"] for c in raw_customers if c.get("id")]

    enriched_customers = []
    for cid in customer_ids:
        cust = _call_clover(
            f"{merchant_id}/customers/{cid}",
            {"expand": "phoneNumbers"},
        )
        if cust:
            # Normalise phoneNumbers list
            raw_phones = cust.get("phoneNumbers")
            if isinstance(raw_phones, dict):
                cust["phoneNumbers"] = _extract_list(raw_phones, "elements")
            enriched_customers.append(cust)

    order_data["customers"] = enriched_customers
    return order_data


def is_online_order(order_data: dict) -> bool:
    """Return ``True`` if the Clover order is an online/pickup/delivery order.

    Checks ``orderType.name`` and ``orderType.label`` (top-level and inside
    ``orderCart``).
    """
    order_types_to_check: list[dict] = []

    # Top-level orderType
    ot = order_data.get("orderType") or {}
    if ot:
        order_types_to_check.append(ot)

    # orderCart.orderType
    cart = order_data.get("orderCart") or {}
    ot2 = cart.get("orderType") or {}
    if ot2:
        order_types_to_check.append(ot2)

    for ot in order_types_to_check:
        type_str = (ot.get("name") or ot.get("label") or "").lower()
        if type_str in ("online", "pickup", "pick-up", "delivery", "online order"):
            return True
        # Also catch things like "Clover In-store Pickup"
        if "pickup" in type_str or "pick up" in type_str:
            return True

    return False


def extract_customer_info(order_data: dict) -> tuple[str, str]:
    """Extract ``(name, phone)`` from a Clover order.

    Expects ``order_data["customers"]`` to be a flat list of enriched customer
    objects (as set by ``fetch_clover_order``).

    Returns ``("", "")`` when no data is available.
    """
    customers = order_data.get("customers") or []
    if not customers:
        return "", ""

    customer = customers[0]
    first = (customer.get("firstName") or "").strip()
    last = (customer.get("lastName") or "").strip()
    name = f"{first} {last}".strip() or (customer.get("displayName") or "").strip()

    phone = ""
    phones = customer.get("phoneNumbers") or []
    if phones:
        phone = _normalize_phone(phones[0].get("phoneNumber") or "")

    return name, phone


def extract_items_summary(order_data: dict) -> str:
    """Build a human-readable summary string from the order's line items."""
    # Try top-level lineItems (normalised by fetch_clover_order), then orderCart
    line_items = (
        order_data.get("lineItems")
        or _extract_list(order_data.get("orderCart") or {}, "lineItems")
        or []
    )
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
        f"Thank you!\n\n"
        f"Reply STOP to opt out."
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
