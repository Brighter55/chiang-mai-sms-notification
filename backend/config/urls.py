from django.contrib import admin
from django.urls import include, path

from orders.views import LoginView, LogoutView, MeView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("orders.urls")),
    path("api/", include("subscribers.urls")),
    path("api/login/", LoginView.as_view(), name="login"),
    path("api/logout/", LogoutView.as_view(), name="logout"),
    path("api/me/", MeView.as_view(), name="me"),
]
