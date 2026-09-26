"""Tests for the Clover sync path.

The sync used to cost one Clover request per order (plus one per customer),
which is what made a dashboard refresh take ~20 seconds.  These tests pin the
cost to a constant so it can't drift back.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from . import services, views
from .models import Order


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
