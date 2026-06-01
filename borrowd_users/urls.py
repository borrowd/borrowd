from django.urls import path

from .views import (
    CustomSignupView,
    delete_account_view,
    delete_profile_photo_view,
    inventory_view,
    profile_deleted_view,
    profile_view,
    public_profile_view,
    search_terms_export_view,
)

urlpatterns = [
    path("", profile_view, name="profile"),
    path("delete-photo/", delete_profile_photo_view, name="profile-delete-photo"),
    path("profile-deleted/", profile_deleted_view, name="profile-deleted"),
    path("search-terms/export/", search_terms_export_view, name="search-terms-export"),
    path("signup/", CustomSignupView.as_view(), name="custom_signup"),
    path("inventory/", inventory_view, name="profile-inventory"),
    path("delete/", delete_account_view, name="account-delete"),
    path("<int:user_id>/", public_profile_view, name="public-profile"),
]
