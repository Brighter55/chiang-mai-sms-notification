"""Seed a throwaway database for the Playwright run.

With no arguments this lays down the standard fixture the dashboard suite
expects: one pending order from today, one already notified today, and one from a
few days back so the "older orders" toggle has something to reveal.

Pass ``--json-file`` to seed a different shape instead, which is how a bug that
depends on specific data gets reproduced (an order with no phone, a very old
order, a cancelled one). Orders cannot be created through the API — the
serializers are read-only — so this command is the only way to put data in front
of the dashboard.

Format::

    {
      "orders": [
        {
          "clover_order_id": "BUG00001",
          "customer_name": "No Phone",
          "customer_phone": "",
          "items_summary": "Pad Thai x2",
          "status": "pending",
          "minutes_ago": 10
        }
      ],
      "review_requests": [
        {
          "clover_order_id": "BUG00001",
          "status": "sent",
          "minutes_ago": 4320
        }
      ]
    }

``minutes_ago`` backdates ``created_at`` (1440 = one day). Everything except
``clover_order_id`` is optional.

A ``review_requests`` entry records that a phone has already been asked for a
Google review. It names the order rather than the phone: ``recipient_phone`` is
derived from that order's ``customer_phone``, so a fixture cannot claim a phone
was asked while pointing at an order belonging to somebody else.
"""

import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from orders.models import NotificationLog, Order, ReviewRequest

# The spec logs in with these. They are only ever used against the throwaway E2E
# database (see scripts/e2e-backend.mjs), never a real one.
E2E_USERNAME = "e2e-staff"
E2E_PASSWORD = "e2e-password"

DEFAULT_ORDERS = [
    {
        "clover_order_id": "E2E00001",
        "customer_name": "Som Chai",
        "customer_phone": "+13145551234",
        "items_summary": "Pad Thai x2, Thai Tea",
        "status": "pending",
        "minutes_ago": 5,
    },
    {
        "clover_order_id": "E2E00002",
        "customer_name": "Nok Ratana",
        "customer_phone": "+13145559999",
        "items_summary": "Green Curry",
        "status": "notified",
        "minutes_ago": 2,
    },
    {
        "clover_order_id": "E2E00003",
        "customer_name": "Anong P",
        "customer_phone": "+13145550000",
        "items_summary": "Pad See Ew",
        "status": "pending",
        "minutes_ago": 3 * 24 * 60,
    },
    # No phone number: the Send button must be disabled rather than letting staff
    # click into an API 400. Guards a real UI invariant — see e2e/no-phone.spec.ts.
    {
        "clover_order_id": "E2E00004",
        "customer_name": "Walk In",
        "customer_phone": "",
        "items_summary": "Khao Soi",
        "status": "pending",
        "minutes_ago": 8,
    },
    # Cancelled: the one status with no overflow menu, because there is nothing
    # left to act on. Deliberately today-scoped so the "older orders" toggle still
    # has exactly one order behind it.
    {
        "clover_order_id": "E2E00005",
        "customer_name": "Cancel Kim",
        "customer_phone": "+13145552222",
        "items_summary": "Thai Fried Rice",
        "status": "cancelled",
        "minutes_ago": 15,
    },
]

# One order whose customer has already been asked for a review, so the "send
# again?" branch of the confirmation dialog is exercised against real database
# state rather than a stub. 3 days back, so the copy has something to say.
DEFAULT_REVIEW_REQUESTS = [
    {
        "clover_order_id": "E2E00002",
        "minutes_ago": 3 * 24 * 60,
    },
]

DEFAULT_SPEC = {
    "orders": DEFAULT_ORDERS,
    "review_requests": DEFAULT_REVIEW_REQUESTS,
}


class Command(BaseCommand):
    help = "Seed the E2E database with a login and a set of orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json-file",
            metavar="PATH",
            help=(
                "Seed the orders described in this JSON file instead of the "
                "default fixture. Used to reproduce bugs that need specific data."
            ),
        )

    def handle(self, *args, **options):
        spec = DEFAULT_SPEC
        json_file = options.get("json_file")
        if json_file:
            spec = self._read_spec(json_file)

        self._seed(spec)

    def _read_spec(self, json_file: str) -> dict:
        path = Path(json_file)
        if not path.exists():
            raise CommandError(f"No such seed file: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}") from None

        orders = payload.get("orders") if isinstance(payload, dict) else None
        if not isinstance(orders, list):
            raise CommandError(f'{path} must be an object with an "orders" array')

        review_requests = payload.get("review_requests", [])
        if not isinstance(review_requests, list):
            raise CommandError(f'{path}: "review_requests" must be an array')

        return {"orders": orders, "review_requests": review_requests}

    def _seed(self, spec: dict) -> None:
        # Idempotent: Playwright may start the server more than once.
        Order.objects.all().delete()
        NotificationLog.objects.all().delete()
        ReviewRequest.objects.all().delete()
        User.objects.filter(username=E2E_USERNAME).delete()
        User.objects.create_user(E2E_USERNAME, password=E2E_PASSWORD)

        now = timezone.now()
        orders_by_clover_id = {}

        for order_spec in spec["orders"]:
            clover_order_id = order_spec.get("clover_order_id")
            if not clover_order_id:
                raise CommandError(f"Every order needs a clover_order_id: {order_spec!r}")

            status = order_spec.get("status", Order.Status.PENDING)
            valid = {choice.value for choice in Order.Status}
            if status not in valid:
                raise CommandError(
                    f"{clover_order_id}: status must be one of {sorted(valid)}, got {status!r}"
                )

            minutes_ago = order_spec.get("minutes_ago", 0)
            created_at = now - timedelta(minutes=minutes_ago)

            order = Order.objects.create(
                clover_order_id=clover_order_id,
                customer_name=order_spec.get("customer_name", ""),
                customer_phone=order_spec.get("customer_phone", ""),
                items_summary=order_spec.get("items_summary", ""),
                status=status,
                notified_at=created_at if status == Order.Status.NOTIFIED else None,
            )
            # created_at is auto_now_add, so it can only be backdated with an
            # update() that bypasses the field's automatic handling.
            Order.objects.filter(pk=order.pk).update(created_at=created_at)
            orders_by_clover_id[clover_order_id] = order

        for review_spec in spec.get("review_requests", []):
            self._seed_review(review_spec, orders_by_clover_id, now)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Order.objects.count()} orders, "
                f"{ReviewRequest.objects.count()} review requests "
                f"and user '{E2E_USERNAME}'."
            )
        )

    def _seed_review(self, spec: dict, orders_by_clover_id: dict, now) -> None:
        clover_order_id = spec.get("clover_order_id")
        order = orders_by_clover_id.get(clover_order_id)
        if order is None:
            raise CommandError(
                f"review_requests names {clover_order_id!r}, which no order in this "
                "spec defines — the phone is derived from that order."
            )

        status = spec.get("status", ReviewRequest.Status.SENT)
        valid = {choice.value for choice in ReviewRequest.Status}
        if status not in valid:
            raise CommandError(
                f"{clover_order_id}: review status must be one of {sorted(valid)}, "
                f"got {status!r}"
            )

        # A sent review needs a SID: without one the app treats the row as an
        # attempt that never reached Twilio, and the dialog would not warn.
        twilio_sid = spec.get(
            "twilio_sid",
            "SM_SEEDED" if status == ReviewRequest.Status.SENT else None,
        )
        created_at = now - timedelta(minutes=spec.get("minutes_ago", 0))

        review = ReviewRequest.objects.create(
            order=order,
            recipient_phone=spec.get("recipient_phone") or order.customer_phone,
            message_body="seeded by seed_e2e",
            status=status,
            twilio_sid=twilio_sid,
        )
        ReviewRequest.objects.filter(pk=review.pk).update(created_at=created_at)
