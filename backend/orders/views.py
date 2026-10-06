import logging
import threading

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count, OuterRef, Subquery
from django.middleware.csrf import get_token
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationLog, Order, ReviewRequest
from .serializers import (
    NotificationLogSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    ReviewRequestSerializer,
)
from .services import (
    attach_customer_data,
    extract_customer_info,
    extract_items_summary,
    fetch_customer_map,
    is_online_order,
    list_recent_clover_orders,
    order_customer_ids,
    send_order_notification,
    send_review_request,
)

logger = logging.getLogger(__name__)

# Max orders processed in a single manual sync (keeps Refresh snappy)
SYNC_ORDER_CAP = 50

# Held for the duration of a sync so two overlapping Refreshes (or React's
# dev-mode double-mount) can't crawl Clover at the same time. Process-local,
# which is all this needs on a single worker.
_sync_lock = threading.Lock()


def _orders_to_sync(merchant_id: str) -> tuple[list[dict], int]:
    """Recent Clover orders worth syncing, newest first, plus a skip count.

    Drops orders already handled locally and orders whose type isn't one we
    notify for (see ``is_online_order``), then caps what's left at
    ``SYNC_ORDER_CAP``.  The list endpoint already carries the order type, so
    none of this costs an extra request.
    """
    skip_ids = set(
        Order.objects.exclude(status=Order.Status.PENDING).values_list(
            "clover_order_id", flat=True
        )
    )

    candidates: list[dict] = []
    seen: set[str] = set()
    skipped = 0
    for order_data in list_recent_clover_orders(merchant_id):
        order_uuid = order_data["id"]
        if order_uuid in skip_ids or order_uuid in seen:
            continue
        if not is_online_order(order_data):
            ot = order_data.get("orderType") or {}
            # Log both fields verbatim: when a real order type is missing from
            # the dashboard, this line is how we learn the exact string Clover
            # sends for it (see _ACCEPTED_ORDER_TYPE_KEYWORDS).
            logger.info(
                "Order %s has an order type we don't notify for "
                "(name=%r label=%r) — skipped",
                order_uuid,
                ot.get("name"),
                ot.get("label"),
            )
            skipped += 1
            continue
        seen.add(order_uuid)
        candidates.append(order_data)
        if len(candidates) >= SYNC_ORDER_CAP:
            break

    return candidates, skipped


def _save_orders(orders: list[Order]) -> tuple[int, int]:
    """Insert or update *orders* in a single statement.

    Returns ``(created, updated)``.  Only the customer and item fields are
    refreshed on an existing row — ``status`` and ``notified_at`` are left
    alone, so a sync can never undo a notification.
    """
    if not orders:
        return 0, 0

    order_ids = [order.clover_order_id for order in orders]
    existing = set(
        Order.objects.filter(clover_order_id__in=order_ids).values_list(
            "clover_order_id", flat=True
        )
    )
    Order.objects.bulk_create(
        orders,
        update_conflicts=True,
        unique_fields=["clover_order_id"],
        update_fields=["customer_name", "customer_phone", "items_summary"],
    )
    created = sum(1 for order_id in order_ids if order_id not in existing)
    return created, len(order_ids) - created


def _run_sync(merchant_id: str) -> dict:
    """Pull recent Clover orders into local records and summarise the result.

    Two requests cover the whole sync — the order list (with line items, order
    types and customers expanded) and one sweep of the merchant's customers
    for their phone numbers — so the cost no longer grows with the number of
    orders.
    """
    candidates, skipped = _orders_to_sync(merchant_id)

    # One customer lookup for the whole batch, instead of one call per customer
    customer_map = fetch_customer_map(
        merchant_id,
        {cid for order_data in candidates for cid in order_customer_ids(order_data)},
    )

    new_orders: list[Order] = []
    for order_data in candidates:
        attach_customer_data(order_data, customer_map)
        customer_name, customer_phone = extract_customer_info(order_data)
        if not customer_name or not customer_phone:
            logger.info(
                "Order %s (%s) has no name or phone — skipped",
                order_data["id"],
                customer_name or "no customer",
            )
            skipped += 1
            continue
        new_orders.append(
            Order(
                clover_order_id=order_data["id"],
                customer_name=customer_name,
                customer_phone=customer_phone,
                items_summary=extract_items_summary(order_data),
            )
        )

    created, updated = _save_orders(new_orders)
    logger.info(
        "Sync complete: %d created, %d updated, %d skipped", created, updated, skipped
    )
    return {"created": created, "updated": updated, "skipped": skipped, "errors": 0}


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
        if self.action == "list":
            # Counting notifications here saves a query per row in the serializer.
            #
            # order_by is required, not decorative. Annotating with an aggregate
            # makes Django drop Meta.ordering, leaving the SQL with no ORDER BY at
            # all. DRF paginates this endpoint and the dashboard only ever reads
            # page 1, so an unordered list is not guaranteed to hold the newest
            # orders — which shows up as "orders are missing from the dashboard".
            #
            # The review state is a correlated Subquery, not a second Count():
            # another join-backed aggregate would multiply the rows the first one
            # counts, and notification_count would silently double. It has to stay
            # a bare Subquery too — wrapping it in Coalesce() or any other Func
            # makes Django append it to the GROUP BY clause.
            #
            # "Already asked" is per phone, so this correlates on the phone rather
            # than on the order: a regular who orders twice sees the state on both.
            qs = qs.annotate(
                notification_count=Count("notifications"),
                review_last_sent_at=Subquery(
                    ReviewRequest.objects.sent()
                    .filter(recipient_phone=OuterRef("customer_phone"))
                    .order_by("-created_at")
                    .values("created_at")[:1]
                ),
            ).order_by("-created_at")
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

        # A Refresh that lands while one is already running would only
        # duplicate the work — report nothing new; the caller reloads the list.
        if not _sync_lock.acquire(blocking=False):
            logger.info("Sync already in progress — duplicate request ignored")
            return Response({"created": 0, "updated": 0, "skipped": 0, "errors": 0})

        try:
            result = _run_sync(settings.CLOVER_MERCHANT_ID)
        except Exception:
            logger.exception("Order sync failed")
            return Response(
                {"error": "Sync failed — see the server logs."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        finally:
            _sync_lock.release()

        return Response(result)

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

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """Text the customer a Google review link.

        Two deliberate differences from ``send`` above. There is no
        409-if-already-done guard, because asking twice is a legitimate decision
        the dashboard puts to staff in a confirmation dialog — the API must not
        refuse the send they then confirm. And the pickup status is not consulted
        at all: a review is usually asked for after collection, which is exactly
        when the order is already notified.
        """
        order = self.get_object()

        if not settings.GOOGLE_REVIEW_URL:
            return Response(
                {"error": "Google review link not configured. Set GOOGLE_REVIEW_URL."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not order.customer_phone:
            return Response(
                {"error": "Order has no customer phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        review_request = send_review_request(order)
        serializer = ReviewRequestSerializer(review_request)
        response_status = (
            status.HTTP_200_OK
            if review_request.status == ReviewRequest.Status.SENT
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
