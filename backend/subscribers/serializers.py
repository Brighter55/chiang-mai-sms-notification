import phonenumbers
from django.conf import settings
from rest_framework import serializers

from .models import OptInSubscriber


class OptInSubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptInSubscriber
        fields = ["id", "phone", "created_at"]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {
            "phone": {
                "required": False,
                "allow_blank": True,
                "max_length": 16,
            }
        }

    def validate_phone(self, value: str) -> str:
        """Validate and normalize the phone number to E.164 format."""
        if not value:
            return value

        try:
            parsed = phonenumbers.parse(value, settings.DEFAULT_PHONE_REGION)
        except phonenumbers.NumberParseException:
            # `from None` — the parser's exception is an implementation detail;
            # the caller gets the clean validation message instead of a chained
            # traceback.
            raise serializers.ValidationError(
                "Enter a valid phone number (e.g., 314-555-0123)."
            ) from None

        if not phonenumbers.is_valid_number(parsed):
            raise serializers.ValidationError(
                "This phone number doesn't appear to be valid. Please check and try again."
            )

        normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

        # Check uniqueness on the normalized value (UniqueValidator runs
        # before field-level validation, so it checks the raw input —
        # we need to check again after normalization).
        if OptInSubscriber.objects.filter(phone=normalized).exists():
            raise serializers.ValidationError(
                "This phone number is already subscribed for SMS updates."
            )

        return normalized
