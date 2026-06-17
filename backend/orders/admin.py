from django.contrib import admin

from .models import NotificationLog, Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "clover_order_id",
        "customer_name",
        "customer_phone",
        "status",
        "created_at",
        "notified_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["clover_order_id", "customer_name", "customer_phone"]
    readonly_fields = ["clover_order_id", "created_at"]


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = [
        "order",
        "recipient_phone",
        "status",
        "twilio_sid",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["recipient_phone", "twilio_sid"]
    readonly_fields = ["created_at"]
