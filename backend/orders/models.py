from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        NOTIFIED = "notified", "Notified"
        CANCELLED = "cancelled", "Cancelled"

    clover_order_id = models.CharField(max_length=64, unique=True, db_index=True)
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=20)
    items_summary = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.clover_order_id} — {self.customer_name} ({self.status})"


class NotificationLog(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    recipient_phone = models.CharField(max_length=20)
    message_body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    twilio_sid = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification for {self.order.clover_order_id} — {self.status}"


class ReviewRequestQuerySet(models.QuerySet):
    def sent(self):
        """Rows Twilio actually accepted — the one definition of "already asked".

        A row is written *before* the API call, so that a crash still leaves an
        audit trail. That makes ``status=sent`` alone a claim rather than proof:
        a process that dies mid-send leaves exactly that, with no SID. Requiring
        the SID keeps "already asked" meaning "a message really went out" —
        otherwise one crash would permanently tell staff this customer had been
        asked when nothing was ever sent.
        """
        return self.filter(status=ReviewRequest.Status.SENT, twilio_sid__isnull=False)


class ReviewRequest(models.Model):
    """A record of asking one customer, by phone, to leave a Google review.

    Keyed on the phone rather than the order on purpose: "have we already asked
    this person?" is a question about the customer, and a regular who orders
    twice must not be asked again without staff noticing. Rows are appended, not
    updated in place, so asking twice leaves two rows and the table doubles as
    the audit trail — the same shape, for the same reason, as NotificationLog.
    """

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    # SET_NULL, not CASCADE. What stops a repeat ask is the phone, so a deleted
    # order must not take the row that remembers this customer with it —
    # otherwise tidying up one old order silently re-opens them to being asked.
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_requests",
    )
    recipient_phone = models.CharField(max_length=20, db_index=True)
    message_body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    twilio_sid = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ReviewRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # The lookup this table exists to serve: the latest sent review for
            # a phone, which the order list correlates against on every page.
            models.Index(fields=["recipient_phone", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"Review request for {self.recipient_phone} — {self.status}"
