from django.urls import path
from django.views.generic import RedirectView

from .views import (
    account_settings_view,
    delete_account_view,
    messaging_settings_view,
    security_settings_view,
)

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="settings-security"),
        name="settings",
    ),
    path("security/", security_settings_view, name="settings-security"),
    path("messaging/", messaging_settings_view, name="settings-messaging"),
    path("account/", account_settings_view, name="settings-account"),
    path("account/delete/", delete_account_view, name="account-delete"),
]
