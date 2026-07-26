from django.urls import path

from .views import (
    mark_all_notifications_read,
    mark_notification_read,
    notification_inbox_view,
    notification_popup_view,
    open_notification,
    remove_all_app_notifications,
    remove_app_notification,
)

urlpatterns = [
    path("", notification_inbox_view, name="notification-inbox"),
    path("<int:pk>/read/", mark_notification_read, name="notification-mark-read"),
    path("read-all/", mark_all_notifications_read, name="notification-mark-all-read"),
    path("<int:pk>/delete/", remove_app_notification, name="notification-delete"),
    path("delete-all/", remove_all_app_notifications, name="notification-delete-all"),
    path("popup/", notification_popup_view, name="notification-popup"),
    path("<int:pk>/open/", open_notification, name="notification-open"),
]
