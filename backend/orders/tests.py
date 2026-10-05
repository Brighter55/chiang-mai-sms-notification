"""Tests for the Clover sync path and the SMS notify path.

The sync used to cost one Clover request per order (plus one per customer),
which is what made a dashboard refresh take ~20 seconds.  Those tests pin the
cost to a constant so it can't drift back.

The SMS tests cover the code that texts real customers.  Nothing here touches
Twilio — the client is stubbed — but the outcomes are pinned hard, because a
regression on this path either texts someone twice or marks an order notified
when no message was ever sent.
"""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from twilio.base.exceptions import TwilioRestException

from . import services, views
from .models import NotificationLog, Order


def _order(order_id: str, *, order_type: str = "Online", customer_id: str | None = None):
    """A Clover order as the expanded list endpoint returns it."""
    data = {
        "id": order_id,
        "modifiedTime": 1000,
        "orderType": {"name": order_type},
        "lineItems": {"elements": [{"name": "Pad Thai", "quantity": 2}]},
    }
    if customer_id:
        # Clover expands an order's customers to bare {id, href} references —
        # no name, no phone. The fixture must match that or it hides bugs:
        # an earlier version put the name in here, which masked a regression
        # where synced orders were dropped for having "no customer".
        data["customers"] = {
            "elements": [
                {
                    "id": customer_id,
                    "href": f"https://api.clover.com/v3/merchants/MID/customers/{customer_id}",
                }
            ]
        }
    return data


def _customer(customer_id: str, phone: str = "3145551234"):
    """A customer as the customers endpoint returns it."""
    return {
        "id": customer_id,
        "firstName": "Som",
        "lastName": "Chai",
        "phoneNumbers": {"elements": [{"phoneNumber": phone}]},
    }


class OrderTypeMatchingTests(TestCase):
    """Which Clover order types the dashboard pulls in.

    The merchant's own types ("Take Out", "Waiting Here") must sync and
    dine-in must not.  Matching is deliberately tolerant: order types are
    merchant-defined, so the same type gets spelled inconsistently.
    """

    def test_accepted_order_types(self):
        for order_type in (
            "Online",
            "Online Order",
            "In-store Pickup",
            "Clover In-store Pickup",
            "Pick-Up",
            "Delivery",
            "Take Out",
            "Take-Out",
            "Takeout",
            "Waiting Here",
            "waiting here",
        ):
            with self.subTest(order_type=order_type):
                order = _order("o1", order_type=order_type)
                self.assertTrue(services.is_online_order(order))

    def test_dropped_order_types(self):
        for order_type in ("Dine-In", "Dine In", "Catering", "Unknown", ""):
            with self.subTest(order_type=order_type):
                order = _order("o1", order_type=order_type)
                self.assertFalse(services.is_online_order(order))

    def test_label_is_checked_when_name_is_missing(self):
        """Clover doesn't always populate ``name``; the label must still count."""
        order = {"orderType": {"label": "Waiting Here"}}
        self.assertTrue(services.is_online_order(order))

    def test_order_cart_order_type_is_checked(self):
        order = {"orderCart": {"orderType": {"name": "Take Out"}}}
        self.assertTrue(services.is_online_order(order))


class SyncCallCountTests(TestCase):
    """A refresh must not cost a Clover request per order."""

    def setUp(self):
        self.listed_orders: list[dict] = []
        self.customers: list[dict] = []
        self.individual_customers: dict[str, dict] = {}
        self.calls: list[str] = []

        def fake_call(path, params=None):
            self.calls.append(path)
            if path.endswith("/orders"):
                return {"elements": self.listed_orders}
            if path.endswith("/customers"):
                return {"elements": self.customers}
            if "/customers/" in path:
                return self.individual_customers.get(path.rsplit("/", 1)[-1])
            raise AssertionError(f"Unexpected Clover call: {path}")

        patcher = mock.patch.object(services, "_call_clover", side_effect=fake_call)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cost_does_not_grow_with_the_number_of_orders(self):
        self.listed_orders = [_order(f"o{i}", customer_id=f"c{i}") for i in range(20)]
        self.customers = [_customer(f"c{i}") for i in range(20)]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 20)
        # One list call + one customers sweep, regardless of order count
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(Order.objects.count(), 20)

    def test_customer_name_comes_from_the_lookup_not_the_order(self):
        """The order's customer ref has no name — it must be merged in.

        Without this the order is skipped as "no customer" and silently
        vanishes from the dashboard.
        """
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = [_customer("c1")]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 1)
        self.assertEqual(Order.objects.get().customer_name, "Som Chai")

    def test_a_customer_the_lookup_cannot_resolve_is_skipped(self):
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = []  # sweep finds nobody, and the fallback finds nobody

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_phones_are_normalised_to_e164(self):
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = [_customer("c1", phone="3145551234")]

        views._run_sync("MID")

        self.assertEqual(Order.objects.get().customer_phone, "+13145551234")

    def test_dine_in_orders_are_dropped_without_extra_calls(self):
        self.listed_orders = [_order("online", customer_id="c1")] + [
            _order(f"dine{i}", order_type="Dine-In") for i in range(5)
        ]
        self.customers = [_customer("c1")]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 5)
        self.assertEqual(len(self.calls), 2)

    def test_take_out_and_waiting_here_orders_reach_the_dashboard(self):
        """The merchant's own order types sync alongside In-store Pickup."""
        self.listed_orders = [
            _order("takeout", order_type="Take Out", customer_id="c1"),
            _order("waiting", order_type="Waiting Here", customer_id="c2"),
            _order("dine", order_type="Dine-In", customer_id="c3"),
        ]
        self.customers = [_customer("c1"), _customer("c2")]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(
            set(Order.objects.values_list("clover_order_id", flat=True)),
            {"takeout", "waiting"},
        )

    def test_orders_without_a_usable_phone_are_skipped(self):
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = [_customer("c1", phone="")]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_already_notified_orders_are_never_refetched(self):
        order = Order.objects.create(
            clover_order_id="o1",
            customer_name="Som Chai",
            customer_phone="+13145551234",
            status=Order.Status.NOTIFIED,
        )
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = [_customer("c1")]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 0)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.NOTIFIED)

    def test_sync_does_not_clobber_the_status_of_an_existing_order(self):
        Order.objects.create(
            clover_order_id="o1",
            customer_name="Old Name",
            customer_phone="+13145550000",
        )
        self.listed_orders = [_order("o1", customer_id="c1")]
        self.customers = [_customer("c1")]

        result = views._run_sync("MID")

        self.assertEqual(result["updated"], 1)
        order = Order.objects.get(clover_order_id="o1")
        self.assertEqual(order.customer_phone, "+13145551234")
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertIsNone(order.notified_at)

    def test_the_cap_limits_orders_synced(self):
        self.listed_orders = [
            _order(f"o{i}", customer_id=f"c{i}") for i in range(views.SYNC_ORDER_CAP + 10)
        ]
        self.customers = [_customer(f"c{i}") for i in range(views.SYNC_ORDER_CAP)]

        result = views._run_sync("MID")

        self.assertEqual(result["created"], views.SYNC_ORDER_CAP)

    def test_customer_sweep_falls_back_to_individual_lookups(self):
        self.listed_orders = [
            _order("o1", customer_id="c1"),
            _order("o2", customer_id="missing"),
        ]
        # c1 comes back from the sweep; "missing" does not
        self.customers = [_customer("c1")]
        self.individual_customers = {"missing": _customer("missing", phone="3145559999")}

        result = views._run_sync("MID")

        self.assertEqual(result["created"], 2)
        self.assertIn("+13145559999", Order.objects.values_list("customer_phone", flat=True))

    def test_bulk_customer_lookups_replace_per_customer_requests(self):
        """The sweep is what used to be one request per customer."""
        customers = [_customer(f"c{i}") for i in range(20)]
        self.listed_orders = [_order(f"o{i}", customer_id=f"c{i}") for i in range(20)]
        self.customers = customers

        views._run_sync("MID")

        # 20 customers, but only one call to look them up
        customer_calls = [p for p in self.calls if p.endswith("/customers")]
        self.assertEqual(len(customer_calls), 1)


class SyncEndpointTests(TestCase):
    """The sync action itself — guarding against overlapping refreshes."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("staff", password="pw"))

    @override_settings(CLOVER_API_TOKEN="token", CLOVER_MERCHANT_ID="MID")
    def test_overlapping_refresh_reports_nothing_new(self):
        """React's dev-mode double-mount fires two syncs; only one may crawl Clover."""
        with mock.patch.object(services, "_call_clover") as call:
            # Hold the lock as if a sync were already in flight
            views._sync_lock.acquire(blocking=False)
            self.addCleanup(views._sync_lock.release)

            response = self.client.post("/api/orders/sync/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 0)
        call.assert_not_called()


class CustomerMapTests(TestCase):
    """The bulk sweep is what replaced the per-customer request."""

    def test_stops_early_once_every_wanted_id_is_found(self):
        calls = []

        def fake_call(path, params=None):
            calls.append((path, params))
            return {"elements": [_customer("c1"), _customer("c2")]}

        with mock.patch.object(services, "_call_clover", side_effect=fake_call):
            customers = services.fetch_customer_map("MID", {"c1", "c2"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(customers), {"c1", "c2"})

    def test_keeps_the_whole_record_not_just_the_phone(self):
        """The name is only on the customer record — dropping it loses orders."""

        def fake_call(path, params=None):
            return {"elements": [_customer("c1")]}

        with mock.patch.object(services, "_call_clover", side_effect=fake_call):
            customers = services.fetch_customer_map("MID", {"c1"})

        self.assertEqual(customers["c1"]["firstName"], "Som")
        self.assertEqual(customers["c1"]["lastName"], "Chai")

    def test_no_lookup_at_all_when_nothing_is_wanted(self):
        with mock.patch.object(services, "_call_clover") as call:
            self.assertEqual(services.fetch_customer_map("MID", set()), {})
        call.assert_not_called()


# ---------------------------------------------------------------------------
# SMS notification
# ---------------------------------------------------------------------------

def _notifiable_order(**overrides) -> Order:
    """A saved Order that is ready to be notified."""
    fields = {
        "clover_order_id": "o1",
        "customer_name": "Som Chai",
        "customer_phone": "+13145551234",
    }
    fields.update(overrides)
    return Order.objects.create(**fields)


@override_settings(
    TWILIO_ACCOUNT_SID="AC_test",
    TWILIO_AUTH_TOKEN="token_test",
    TWILIO_PHONE_NUMBER="+13145550000",
    MERCHANT_NAME="Chiang Mai",
)
class SmsMessageTests(TestCase):
    """The message body is a compliance surface, so its shape is pinned."""

    def test_carries_the_opt_out_line(self):
        message = services.build_sms_message(_notifiable_order())
        self.assertIn("Reply STOP to opt out.", message)

    def test_names_the_merchant_and_says_why(self):
        message = services.build_sms_message(_notifiable_order())
        self.assertIn("Chiang Mai", message)
        self.assertIn("ready for pickup", message)

    def test_never_includes_the_customer_name_or_the_items(self):
        """The body is deliberately generic.

        A name or an item list would land on whatever lock screen the message
        reaches. That is a privacy decision, not an oversight — don't "improve"
        the template by adding them.
        """
        order = _notifiable_order(
            customer_name="Som Chai",
            items_summary="Pad Thai x2, Thai Tea",
        )

        message = services.build_sms_message(order)

        self.assertNotIn("Som Chai", message)
        self.assertNotIn("Pad Thai", message)


@override_settings(
    TWILIO_ACCOUNT_SID="AC_test",
    TWILIO_AUTH_TOKEN="token_test",
    TWILIO_PHONE_NUMBER="+13145550000",
    MERCHANT_NAME="Chiang Mai",
)
class SendOrderNotificationTests(TestCase):
    """Every outcome of the send path. Twilio is stubbed, never called."""

    def _stub_twilio(self, *, sid: str = "SM_TEST_1", error: Exception | None = None):
        """Patch the Twilio client; returns the stub so call args can be asserted."""
        client = mock.MagicMock()
        if error is not None:
            client.messages.create.side_effect = error
        else:
            client.messages.create.return_value.sid = sid
        patcher = mock.patch.object(services, "Client", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def test_success_sends_marks_the_order_notified_and_records_the_sid(self):
        order = _notifiable_order()
        client = self._stub_twilio(sid="SM_ABC")

        log = services.send_order_notification(order)

        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertEqual(log.twilio_sid, "SM_ABC")
        self.assertEqual(log.recipient_phone, "+13145551234")

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.NOTIFIED)
        self.assertIsNotNone(order.notified_at)

        sent = client.messages.create.call_args.kwargs
        self.assertEqual(sent["to"], order.customer_phone)
        self.assertEqual(sent["from_"], settings.TWILIO_PHONE_NUMBER)
        self.assertEqual(sent["body"], log.message_body)

    def test_a_twilio_error_fails_the_log_and_leaves_the_order_pending(self):
        """A failed send must not look like a successful one.

        If the order flipped to notified here, staff would stop chasing a
        customer who was never actually told — which is the entire point of the
        dashboard.
        """
        order = _notifiable_order()
        self._stub_twilio(
            error=TwilioRestException(400, "https://api.twilio.com/x", "Bad number")
        )

        log = services.send_order_notification(order)

        self.assertEqual(log.status, NotificationLog.Status.FAILED)
        self.assertIn("Bad number", log.error_message)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertIsNone(order.notified_at)

    def test_an_unexpected_error_is_handled_the_same_way(self):
        order = _notifiable_order()
        self._stub_twilio(error=RuntimeError("socket exploded"))

        log = services.send_order_notification(order)

        self.assertEqual(log.status, NotificationLog.Status.FAILED)
        self.assertEqual(log.error_message, "Unexpected error sending SMS")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_the_log_is_written_even_when_the_send_fails(self):
        """The log is the audit trail, so it has to outlive a failed attempt."""
        self._stub_twilio(error=RuntimeError("boom"))

        services.send_order_notification(_notifiable_order())

        self.assertEqual(NotificationLog.objects.count(), 1)


@override_settings(
    TWILIO_ACCOUNT_SID="AC_test",
    TWILIO_AUTH_TOKEN="token_test",
    TWILIO_PHONE_NUMBER="+13145550000",
    MERCHANT_NAME="Chiang Mai",
)
class SendEndpointTests(TestCase):
    """POST /api/orders/{id}/send/ — the guards and the status mapping."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("staff", password="pw"))

    def _stub_twilio(self, *, error: Exception | None = None):
        client = mock.MagicMock()
        if error is not None:
            client.messages.create.side_effect = error
        else:
            client.messages.create.return_value.sid = "SM_ENDPOINT"
        patcher = mock.patch.object(services, "Client", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def test_a_successful_send_returns_200(self):
        order = _notifiable_order()
        self._stub_twilio()

        response = self.client.post(f"/api/orders/{order.id}/send/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sent")

    def test_a_failed_send_returns_502(self):
        order = _notifiable_order()
        self._stub_twilio(
            error=TwilioRestException(500, "https://api.twilio.com/x", "nope")
        )

        response = self.client.post(f"/api/orders/{order.id}/send/")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["status"], "failed")

    def test_an_already_notified_order_is_rejected_without_texting_again(self):
        order = _notifiable_order(status=Order.Status.NOTIFIED)
        client = self._stub_twilio()

        response = self.client.post(f"/api/orders/{order.id}/send/")

        self.assertEqual(response.status_code, 409)
        client.messages.create.assert_not_called()

    def test_an_order_without_a_phone_is_rejected_without_texting(self):
        order = _notifiable_order(customer_phone="")
        client = self._stub_twilio()

        response = self.client.post(f"/api/orders/{order.id}/send/")

        self.assertEqual(response.status_code, 400)
        client.messages.create.assert_not_called()

    def test_sending_requires_a_session(self):
        order = _notifiable_order()
        self.client.logout()
        client = self._stub_twilio()

        response = self.client.post(f"/api/orders/{order.id}/send/")

        self.assertIn(response.status_code, (401, 403))
        client.messages.create.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)


# ---------------------------------------------------------------------------
# Order list ordering
# ---------------------------------------------------------------------------

class OrderListOrderingTests(TestCase):
    """GET /api/orders/ must come back newest-first.

    Not cosmetic. Django drops ``Meta.ordering`` the moment a queryset is
    annotated with an aggregate, and ``get_queryset`` annotates for the list
    action — so the SQL had no ORDER BY at all. DRF paginates this endpoint and
    the dashboard only ever reads page 1, so an unordered list is not guaranteed
    to contain the newest orders. That presents as "orders are missing from the
    dashboard", which is the symptom these tests exist to prevent.
    """

    def setUp(self):
        self.client.force_login(User.objects.create_user("staff", password="pw"))

    def _saved_order(self, name: str, *, minutes_ago: int) -> Order:
        order = Order.objects.create(
            clover_order_id=f"o-{name}",
            customer_name=name,
            customer_phone="+13145551234",
        )
        # created_at is auto_now_add, so it can only be backdated via update().
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
        order.refresh_from_db()
        return order

    def test_the_list_comes_back_newest_first(self):
        self._saved_order("oldest", minutes_ago=120)
        self._saved_order("middle", minutes_ago=60)
        self._saved_order("newest", minutes_ago=1)

        response = self.client.get("/api/orders/")

        self.assertEqual(response.status_code, 200)
        names = [row["customer_name"] for row in response.json()["results"]]
        self.assertEqual(names, ["newest", "middle", "oldest"])

    def test_the_list_queryset_is_explicitly_ordered(self):
        """Guards the trap itself, not just the symptom.

        Asserting on ``.ordered`` catches the missing ORDER BY deterministically,
        rather than relying on whichever order a particular database happens to
        return rows in.
        """
        request = APIRequestFactory().get("/api/orders/")
        view = views.OrderViewSet()
        # Normally set by ViewSetMixin.as_view(); needed for initialize_request to
        # resolve self.action, which is what turns the annotate on.
        view.action_map = {"get": "list"}
        view.request = view.initialize_request(request)
        view.format_kwarg = None

        queryset = view.get_queryset()

        # Guard against a vacuous pass: the annotation is precisely what drops
        # Meta.ordering, so if it is absent this test proves nothing.
        self.assertEqual(view.action, "list")
        self.assertIn("notification_count", queryset.query.annotations)
        self.assertTrue(queryset.ordered)

    def test_pagination_does_not_repeat_or_skip_orders(self):
        """The dashboard reads one page, so a page must be a stable slice."""
        for i in range(views.SYNC_ORDER_CAP + 10):
            self._saved_order(f"o{i}", minutes_ago=i)

        first = self.client.get("/api/orders/").json()["results"]
        second = self.client.get("/api/orders/?page=2").json()["results"]

        ids = [row["id"] for row in first + second]
        self.assertEqual(len(ids), views.SYNC_ORDER_CAP + 10)
        self.assertEqual(len(set(ids)), len(ids), "an order appeared on two pages")
