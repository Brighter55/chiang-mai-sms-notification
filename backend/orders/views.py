import json
import logging
import re

from django.conf import settings
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import NotificationLog, Order
from .serializers import (
    NotificationLogSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
)
from .services import (
    extract_customer_info,
    extract_items_summary,
    fetch_clover_order,
    is_online_order,
    send_order_notification,
    verify_clover_signature,
)

logger = logging.getLogger(__name__)

# Regex to extract object type prefix and UUID from an objectId like "O:UUID"
_OBJ_ID_RE = re.compile(r"^([A-Z]+):(.+)$")


# ---------------------------------------------------------------------------
# Clover webhook
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([AllowAny])
def clover_webhook(request):
    """Receive order events from Clover.

    Clover sends **lightweight** webhook payloads with only object IDs and
    event types (CREATE / UPDATE / DELETE).  This handler:

    1. Verifies the ``X-Clover-Signature`` (if a secret is configured).
    2. Parses the payload — expects the format below (may batch multiple
       merchants and events).
    3. For each **Orders** event (``O:…`` objectId) fetches the full order
       from the Clover REST API.
    4. Skips orders that are not *online / pickup / delivery* type.
    5. Skips orders that have no customer phone number.
    6. Creates / updates the local ``Order`` record.

    Webhook payload shape::

        {
            "appId": "…",
            "merchants": {
                "{mId}": [
                    {"objectId": "O:{UUID}", "type": "CREATE", "ts": …},
                    …
                ]
            }
        }
    """
    # -- Verify signature ---------------------------------------------------
    signature = request.headers.get("X-Clover-Signature", "")
    if not verify_clover_signature(request.body, signature):
        logger.warning("Invalid Clover webhook signature")
        return Response(
            {"error": "Invalid signature"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # -- Parse body ---------------------------------------------------------
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return Response(
            {"error": "Invalid JSON"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    merchants = payload.get("merchants", {})
    if not merchants:
        logger.info("Webhook received with no merchant events — ignored")
        return Response({"processed": 0, "skipped": 0, "errors": 0})

    # Check early that we *can* fetch order details
    if not settings.CLOVER_API_TOKEN:
        logger.error("CLOVER_API_TOKEN is not set — cannot fetch order details")
        return Response(
            {"error": "Clover API token not configured. Set CLOVER_API_TOKEN."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # -- Process events -----------------------------------------------------
    created_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0
    events_processed = False

    for merchant_id, events in merchants.items():
        if not events:
            continue

        for event in events:
            try:
                result = _process_single_event(merchant_id, event)
                if result == "created":
                    created_count += 1
                elif result == "updated":
                    updated_count += 1
                elif result == "skipped":
                    skipped_count += 1
                events_processed = True
            except Exception:
                logger.exception("Error processing event %s", event)
                error_count += 1

    if not events_processed:
        return Response(
            {"processed": 0, "skipped": 0, "errors": 0},
            status=status.HTTP_200_OK,
        )

    total_new = created_count + updated_count
    logger.info(
        "Webhook processed: %d created, %d updated, %d skipped, %d errors",
        created_count, updated_count, skipped_count, error_count,
    )
    return Response(
        {
            "processed": total_new,
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "errors": error_count,
        },
        status=status.HTTP_200_OK if total_new == 0 else status.HTTP_201_CREATED,
    )


def _process_single_event(merchant_id: str, event: dict) -> str:
    """Process one Clover webhook event.

    Returns one of ``"created"``, ``"updated"``, ``"skipped"``.
    """
    object_id = (event.get("objectId") or "").strip()
    event_type = (event.get("type") or "").strip().upper()

    if not object_id:
        logger.warning("Webhook event missing objectId — skipped")
        return "skipped"

    # Parse the objectId — we only care about Orders ("O:" prefix)
    m = _OBJ_ID_RE.match(object_id)
    if not m:
        logger.warning("Unrecognised objectId format: %s — skipped", object_id)
        return "skipped"

    obj_prefix, obj_uuid = m.group(1), m.group(2)
    if obj_prefix != "O":
        logger.debug("Ignoring non-order webhook: %s", object_id)
        return "skipped"

    if event_type == "DELETE":
        _handle_order_deleted(obj_uuid)
        return "updated"

    if event_type not in ("CREATE", "UPDATE"):
        logger.debug("Ignoring unknown event type: %s", event_type)
        return "skipped"

    # Fetch full order from Clover API
    order_data = fetch_clover_order(merchant_id, obj_uuid)
    if order_data is None:
        logger.warning("Could not fetch order %s from Clover — skipped", obj_uuid)
        return "skipped"

    # Only process online/pickup/delivery orders
    if not is_online_order(order_data):
        logger.info(
            "Order %s is not an online order (orderType=%s) — skipped",
            obj_uuid,
            (order_data.get("orderCart") or {}).get("orderType", {}).get("name", "unknown"),
        )
        return "skipped"

    # Extract customer info
    customer_name, customer_phone = extract_customer_info(order_data)
    if not customer_name:
        logger.info("Order %s has no customer name — skipped", obj_uuid)
        return "skipped"
    if not customer_phone:
        logger.info(
            "Order %s (%s) has no customer phone — skipped",
            obj_uuid,
            customer_name,
        )
        return "skipped"

    items_summary = extract_items_summary(order_data)

    # Create or update the local record
    try:
        order, created = Order.objects.update_or_create(
            clover_order_id=obj_uuid,
            defaults={
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "items_summary": items_summary,
            },
        )
    except IntegrityError:
        order = Order.objects.get(clover_order_id=obj_uuid)
        created = False

    if created:
        logger.info("Order %s created (%s, %s)", obj_uuid, customer_name, customer_phone)
        return "created"
    else:
        logger.info("Order %s updated (%s, %s)", obj_uuid, customer_name, customer_phone)
        return "updated"


def _handle_order_deleted(order_uuid: str) -> None:
    """Mark a local order as cancelled when Clover sends a DELETE event."""
    try:
        order = Order.objects.get(clover_order_id=order_uuid)
        if order.status != Order.Status.CANCELLED:
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            logger.info("Order %s cancelled via webhook DELETE", order_uuid)
        else:
            logger.debug("Order %s already cancelled", order_uuid)
    except Order.DoesNotExist:
        logger.debug(
            "Received DELETE for unknown order %s — ignored", order_uuid,
        )


# ---------------------------------------------------------------------------
# DRF ViewSets
# ---------------------------------------------------------------------------

class OrderViewSet(viewsets.ModelViewSet):
    """CRUD + custom actions for orders."""

    queryset = Order.objects.all()
    permission_classes = [AllowAny]  # TODO: tighten for production

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        return OrderDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """Trigger an SMS notification for this order."""
        order = self.get_object()

        if order.status == Order.Status.NOTIFIED:
            return Response(
                {"error": "Order has already been notified."},
                status=status.HTTP_409_CONFLICT,
            )

        if not order.customer_phone:
            return Response(
                {"error": "Order has no customer phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notification = send_order_notification(order)
        serializer = NotificationLogSerializer(notification)
        response_status = (
            status.HTTP_200_OK
            if notification.status == NotificationLog.Status.SENT
            else status.HTTP_502_BAD_GATEWAY
        )
        return Response(serializer.data, status=response_status)


class NotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to notification history."""

    queryset = NotificationLog.objects.select_related("order").all()
    serializer_class = NotificationLogSerializer
    permission_classes = [AllowAny]
