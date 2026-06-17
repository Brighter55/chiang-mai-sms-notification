from rest_framework import serializers

from .models import NotificationLog, Order


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "order",
            "recipient_phone",
            "message_body",
            "status",
            "twilio_sid",
            "error_message",
            "created_at",
        ]
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    """Compact representation for the order list."""

    notification_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "clover_order_id",
            "customer_name",
            "customer_phone",
            "items_summary",
            "status",
            "created_at",
            "notified_at",
            "notification_count",
        ]
        read_only_fields = fields

    def get_notification_count(self, obj: Order) -> int:
        return obj.notifications.count()


class OrderDetailSerializer(serializers.ModelSerializer):
    """Full order detail including notification history."""

    notifications = NotificationLogSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "clover_order_id",
            "customer_name",
            "customer_phone",
            "items_summary",
            "status",
            "created_at",
            "notified_at",
            "notifications",
        ]
        read_only_fields = fields
