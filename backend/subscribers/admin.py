from django.contrib import admin

from .models import OptInSubscriber


@admin.register(OptInSubscriber)
class OptInSubscriberAdmin(admin.ModelAdmin):
    list_display = ["phone", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["phone"]
