from django.urls import path

from .views import (
    CustomSignupView,
    delete_profile_photo_view,
    inventory_view,
    profile_view,
    public_profile_view
)

urlpatterns = [
    path("", profile_view, name="profile"),
    path("delete-photo/", delete_profile_photo_view, name="profile-delete-photo"),
    path("signup/", CustomSignupView.as_view(), name="custom_signup"),
    path("inventory/", inventory_view, name="profile-inventory"),
    path("<int:user_id>/", public_profile_view, name="public-profile")
]
