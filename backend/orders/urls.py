from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"orders", views.OrderViewSet, basename="order")
router.register(r"logs", views.NotificationLogViewSet, basename="notificationlog")

urlpatterns = [
    path("webhook/clover/", views.clover_webhook, name="clover-webhook"),
    path("", include(router.urls)),
]
