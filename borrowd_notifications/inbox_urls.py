from django.urls import path

from .views import (
    mark_all_notifications_read,
    mark_notification_read,
    notification_inbox_view,
)

urlpatterns = [
    path("", notification_inbox_view, name="notification-inbox"),
    path("<int:pk>/read/", mark_notification_read, name="notification-mark-read"),
    path("read-all/", mark_all_notifications_read, name="notification-mark-all-read"),
]
