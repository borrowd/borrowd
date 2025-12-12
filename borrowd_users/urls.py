from django.urls import path

from .views import CustomSignupView, inventory_view, profile_view

urlpatterns = [
    path("", profile_view, name="profile"),
    path("signup/", CustomSignupView.as_view(), name="custom_signup"),
    path("inventory/", inventory_view, name="profile-inventory"),
]
