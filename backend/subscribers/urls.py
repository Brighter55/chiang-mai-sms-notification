from django.urls import path

from . import views

urlpatterns = [
    path("opt-in/", views.OptInCreateView.as_view(), name="opt-in-create"),
]
