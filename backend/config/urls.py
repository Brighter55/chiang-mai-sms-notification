from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("orders.urls")),
    path("api/", include("subscribers.urls")),
]
