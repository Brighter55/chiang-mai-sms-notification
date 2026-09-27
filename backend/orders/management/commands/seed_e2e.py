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
      ]
    }

``minutes_ago`` backdates ``created_at`` (1440 = one day). Everything except
``clover_order_id`` is optional.
"""

import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from orders.models import NotificationLog, Order

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
]


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
        orders = DEFAULT_ORDERS
        json_file = options.get("json_file")
        if json_file:
            orders = self._read_spec(json_file)

        self._seed(orders)

    def _read_spec(self, json_file: str) -> list[dict]:
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

        return orders

    def _seed(self, orders: list[dict]) -> None:
        # Idempotent: Playwright may start the server more than once.
        Order.objects.all().delete()
        NotificationLog.objects.all().delete()
        User.objects.filter(username=E2E_USERNAME).delete()
        User.objects.create_user(E2E_USERNAME, password=E2E_PASSWORD)

        now = timezone.now()

        for spec in orders:
            clover_order_id = spec.get("clover_order_id")
            if not clover_order_id:
                raise CommandError(f"Every order needs a clover_order_id: {spec!r}")

            status = spec.get("status", Order.Status.PENDING)
            valid = {choice.value for choice in Order.Status}
            if status not in valid:
                raise CommandError(
                    f"{clover_order_id}: status must be one of {sorted(valid)}, got {status!r}"
                )

            minutes_ago = spec.get("minutes_ago", 0)
            created_at = now - timedelta(minutes=minutes_ago)

            order = Order.objects.create(
                clover_order_id=clover_order_id,
                customer_name=spec.get("customer_name", ""),
                customer_phone=spec.get("customer_phone", ""),
                items_summary=spec.get("items_summary", ""),
                status=status,
                notified_at=created_at if status == Order.Status.NOTIFIED else None,
            )
            # created_at is auto_now_add, so it can only be backdated with an
            # update() that bypasses the field's automatic handling.
            Order.objects.filter(pk=order.pk).update(created_at=created_at)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Order.objects.count()} orders and user '{E2E_USERNAME}'."
            )
        )
