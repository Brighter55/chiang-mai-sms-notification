from rest_framework import serializers

from .models import OptInSubscriber


class OptInSubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptInSubscriber
        fields = ["id", "phone", "created_at"]
        read_only_fields = ["id", "created_at"]
