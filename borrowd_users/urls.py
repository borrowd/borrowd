from django.urls import path

from .views import (
    CustomSignupView,
    delete_profile_photo_view,
    inventory_view,
    profile_view,
    public_profile_view,
    search_terms_export_view,
    menu_badges_drawer_open_view
)

urlpatterns = [
    path("", profile_view, name="profile"),
    path("delete-photo/", delete_profile_photo_view, name="profile-delete-photo"),
    path("search-terms/export/", search_terms_export_view, name="search-terms-export"),
    path("signup/", CustomSignupView.as_view(), name="custom_signup"),
    path("inventory/", inventory_view, name="profile-inventory"),
    path("<int:user_id>/", public_profile_view, name="public-profile"),
    path("menu-badges/drawer-open/",menu_badges_drawer_open_view, name="menu-badges-drawer-open",
),
]
