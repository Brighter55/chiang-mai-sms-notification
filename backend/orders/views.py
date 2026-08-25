import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError
from django.middleware.csrf import get_token
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

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
    list_recent_clover_orders,
    send_order_notification,
)

logger = logging.getLogger(__name__)

# Max orders processed in a single manual sync (keeps Refresh snappy)
SYNC_ORDER_CAP = 50


def _sync_clover_order(merchant_id: str, order_uuid: str) -> str:
    """Fetch one Clover order and create/update the local record.

    Returns one of ``"created"``, ``"updated"``, ``"skipped"``.
    """
    order_data = fetch_clover_order(merchant_id, order_uuid)
    if order_data is None:
        logger.warning("Could not fetch order %s from Clover — skipped", order_uuid)
        return "skipped"

    # Only process online/pickup/delivery orders
    if not is_online_order(order_data):
        ot = order_data.get("orderType") or {}
        ot_name = ot.get("name") or ot.get("label") or "unknown"
        logger.info(
            "Order %s is not an online order (orderType=%s) — skipped",
            order_uuid,
            ot_name,
        )
        return "skipped"

    # Extract customer info
    customer_name, customer_phone = extract_customer_info(order_data)
    if not customer_name:
        logger.info("Order %s has no customer name — skipped", order_uuid)
        return "skipped"
    if not customer_phone:
        logger.info(
            "Order %s (%s) has no customer phone — skipped",
            order_uuid,
            customer_name,
        )
        return "skipped"

    items_summary = extract_items_summary(order_data)

    # Create or update the local record
    try:
        order, created = Order.objects.update_or_create(
            clover_order_id=order_uuid,
            defaults={
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "items_summary": items_summary,
            },
        )
    except IntegrityError:
        order = Order.objects.get(clover_order_id=order_uuid)
        created = False

    if created:
        logger.info("Order %s created (%s, %s)", order_uuid, customer_name, customer_phone)
        return "created"
    logger.info("Order %s updated (%s, %s)", order_uuid, customer_name, customer_phone)
    return "updated"


# ---------------------------------------------------------------------------
# DRF ViewSets
# ---------------------------------------------------------------------------

class OrderViewSet(viewsets.ModelViewSet):
    """CRUD + custom actions for orders."""

    queryset = Order.objects.all()

    # Primary keys are integers — prevents the detail route ("{pk:[0-9]+}")
    # from shadowing the "sync" action URL.
    lookup_value_regex = r"[0-9]+"

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

    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Pull recent orders from Clover and create/update local records."""
        if not settings.CLOVER_API_TOKEN:
            return Response(
                {"error": "Clover API token not configured. Set CLOVER_API_TOKEN."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not settings.CLOVER_MERCHANT_ID:
            return Response(
                {"error": "Clover merchant ID not configured. Set CLOVER_MERCHANT_ID."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        merchant_id = settings.CLOVER_MERCHANT_ID
        recent_orders = list_recent_clover_orders(merchant_id)

        # Orders already sent or cancelled are never re-fetched
        skip_ids = set(
            Order.objects.exclude(status=Order.Status.PENDING).values_list(
                "clover_order_id", flat=True
            )
        )

        created = updated = skipped = errors = 0
        processed = 0
        for order in recent_orders:
            if processed >= SYNC_ORDER_CAP:
                break
            order_uuid = order.get("id")
            if not order_uuid or order_uuid in skip_ids:
                continue
            try:
                result = _sync_clover_order(merchant_id, order_uuid)
            except Exception:
                logger.exception("Error syncing order %s", order_uuid)
                result = "error"
            processed += 1
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            elif result == "skipped":
                skipped += 1
            else:
                errors += 1

        logger.info(
            "Sync complete: %d created, %d updated, %d skipped, %d errors",
            created, updated, skipped, errors,
        )
        return Response({
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        })

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


# ---------------------------------------------------------------------------
# Auth views — session login / logout / current user
# ---------------------------------------------------------------------------


class LoginView(APIView):
    """POST /api/login/ — authenticate and create a session."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {"error": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response({
            "id": user.id,
            "username": user.username,
            "csrf_token": get_token(request),
        })


class LogoutView(APIView):
    """POST /api/logout/ — clear the current session."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"ok": True})


class MeView(APIView):
    """GET /api/me/ — return the current user (or 403 if not logged in)."""

    def get(self, request):
        return Response({
            "id": request.user.id,
            "username": request.user.username,
            "csrf_token": get_token(request),
        })
