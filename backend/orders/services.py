import logging
import re
from datetime import timedelta

import phonenumbers
import requests
from django.conf import settings
from django.utils import timezone
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from .models import NotificationLog, Order

logger = logging.getLogger(__name__)

_NON_DIGIT_RE = re.compile(r"[^\d]+")

# One session for every Clover call — reuses the connection instead of paying
# for a fresh TLS handshake on each request.
_clover_session = requests.Session()


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
        resp = _clover_session.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        logger.error("Timeout fetching %s", url)
    except requests.HTTPError:
        logger.error(
            "Clover API error %s: %s — %s",
            url, resp.status_code, resp.text[:500],
        )
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
    return None


def _normalize_order(order_data: dict) -> dict:
    """Flatten the ``{"elements": [...]}`` wrappers Clover uses for lists.

    Applied to the order and to its cart, so callers can treat ``lineItems``
    and ``customers`` as plain lists no matter which endpoint produced them.
    """
    for container in (order_data, order_data.get("orderCart")):
        if not isinstance(container, dict):
            continue
        for key in ("lineItems", "customers"):
            if isinstance(container.get(key), dict):
                container[key] = _extract_list(container[key], "elements")
    return order_data


def order_customer_ids(order_data: dict) -> list[str]:
    """The customer ids an order references."""
    customers = order_data.get("customers")
    if isinstance(customers, dict):
        customers = _extract_list(customers, "elements")
    if not isinstance(customers, list):
        return []
    return [c["id"] for c in customers if isinstance(c, dict) and c.get("id")]


def _first_phone(customer: dict) -> str:
    """A customer's first phone number, exactly as Clover stores it."""
    phones = customer.get("phoneNumbers")
    if isinstance(phones, dict):
        phones = _extract_list(phones, "elements")
    if not isinstance(phones, list) or not phones:
        return ""
    return (phones[0].get("phoneNumber") or "").strip()


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

    Expects ``order_data["customers"]`` to be a flat list of customer objects
    with their phone numbers attached (see ``fetch_customer_phone_map`` and
    ``attach_customer_phones``).

    Returns ``("", "")`` when no data is available.
    """
    customers = order_data.get("customers") or []
    if not customers:
        return "", ""

    customer = customers[0]
    first = (customer.get("firstName") or "").strip()
    last = (customer.get("lastName") or "").strip()
    name = f"{first} {last}".strip() or (customer.get("displayName") or "").strip()

    return name, _normalize_phone(_first_phone(customer))


def attach_customer_data(order_data: dict, customer_map: dict[str, dict]) -> None:
    """Fill in each of the order's customers from ``fetch_customer_map``.

    Expanding an order returns its customers as bare ``{id, href}`` references
    — no name and no phone — so the fuller record is merged in here.  Merging
    the whole record matters: the name lives only on the customer, and without
    it the order gets skipped for having no customer.
    """
    for customer in order_data.get("customers") or []:
        full = customer_map.get(customer.get("id"))
        if full:
            customer.update(full)


def extract_items_summary(order_data: dict) -> str:
    """Build a human-readable summary string from the order's line items."""
    # Try top-level lineItems (normalised by _normalize_order), then orderCart
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
# Clover order listing (manual sync)
# ---------------------------------------------------------------------------


# Expanding these makes the order list answer a whole sync in one request:
# the line items, the order type (so dine-in can be dropped for free) and the
# customers.
_ORDER_LIST_EXPAND = "lineItems,orderType,orderCart.orderType,customers"

# Page size / page cap for the bulk customer sweep below.
CUSTOMER_PAGE_SIZE = 1000
CUSTOMER_MAX_PAGES = 5


def list_recent_clover_orders(merchant_id: str, limit: int = 100) -> list[dict]:
    """List recent Clover orders within the sync lookback window.

    Returns normalised order objects sorted by ``modifiedTime`` descending, or
    ``[]`` on failure.  Retries once without the ``filter`` param if Clover
    rejects the filter syntax.
    """
    since_ms = int(
        (timezone.now() - timedelta(days=settings.CLOVER_SYNC_LOOKBACK_DAYS))
        .timestamp()
        * 1000
    )

    data = _call_clover(
        f"{merchant_id}/orders",
        {
            "limit": limit,
            "filter": f"modifiedTime>={since_ms}",
            "expand": _ORDER_LIST_EXPAND,
        },
    )
    if data is None:
        # Fallback: fetch the most recent page without a time filter
        data = _call_clover(
            f"{merchant_id}/orders",
            {"limit": limit, "expand": _ORDER_LIST_EXPAND},
        )

    orders = [
        _normalize_order(order)
        for order in _extract_list(data, "elements")
        if order.get("id")
    ]
    orders.sort(key=lambda o: o.get("modifiedTime") or 0, reverse=True)
    return orders


def fetch_customer_map(merchant_id: str, customer_ids: set[str]) -> dict[str, dict]:
    """Map ``customer_id -> full customer record`` for *customer_ids*.

    Orders carry only customer ids, and Clover has no "fetch these ids"
    endpoint, so rather than one request per customer this pages through the
    merchant's customers once and stops as soon as every wanted id has turned
    up.  Anything the sweep missed is then fetched individually, so the result
    is always complete.

    The whole record is kept — not just the phone — because the customer's name
    is the only place an order's name comes from.
    """
    customers_by_id: dict[str, dict] = {}
    wanted = {cid for cid in customer_ids if cid}
    if not wanted:
        return customers_by_id

    for page in range(CUSTOMER_MAX_PAGES):
        data = _call_clover(
            f"{merchant_id}/customers",
            {
                "limit": CUSTOMER_PAGE_SIZE,
                "offset": page * CUSTOMER_PAGE_SIZE,
                "expand": "phoneNumbers",
            },
        )
        customers = _extract_list(data, "elements")
        if not customers:
            break
        for customer in customers:
            cid = customer.get("id")
            if cid in wanted and cid not in customers_by_id:
                customers_by_id[cid] = customer
        if wanted <= customers_by_id.keys() or len(customers) < CUSTOMER_PAGE_SIZE:
            break

    # Fallback for ids the sweep never reached (or a page that failed)
    for cid in wanted - customers_by_id.keys():
        customer = _call_clover(
            f"{merchant_id}/customers/{cid}",
            {"expand": "phoneNumbers"},
        )
        if customer:
            customers_by_id[cid] = customer

    return customers_by_id


# ---------------------------------------------------------------------------
# SMS sending
# ---------------------------------------------------------------------------

def build_sms_message(order: Order) -> str:
    merchant = settings.MERCHANT_NAME
    return (
        f"Your order from {merchant} is ready for pickup! 🛍️\n\n"
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
