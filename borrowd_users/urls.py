from django.urls import path

from .views import CustomSignupView, ProfileUpdateView, inventory_view, profile_view

urlpatterns = [
    path("", profile_view, name="profile"),
    path("edit/", ProfileUpdateView.as_view(), name="profile-edit"),
    path("signup/", CustomSignupView.as_view(), name="custom_signup"),
    path("inventory/", inventory_view, name="profile-inventory"),
]
