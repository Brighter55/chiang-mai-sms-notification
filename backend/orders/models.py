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
