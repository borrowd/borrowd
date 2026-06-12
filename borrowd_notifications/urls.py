from django.urls import path

from .views import (
    bulk_toggle_preferences,
    notification_preferences_view,
    toggle_preference,
)

urlpatterns = [
    path(
        "notifications/", notification_preferences_view, name="notification-preferences"
    ),
    path("notifications/toggle/", toggle_preference, name="notification-toggle"),
    path(
        "notifications/bulk-toggle/",
        bulk_toggle_preferences,
        name="notification-bulk-toggle",
    ),
]
