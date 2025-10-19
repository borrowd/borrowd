from django.urls import path

from .views import ProfileUpdateView, inventory_view, profile_view

urlpatterns = [
    path("", profile_view, name="profile"),
    path("edit/", ProfileUpdateView.as_view(), name="profile-edit"),
    path("inventory/", inventory_view, name="profile-inventory"),
]
