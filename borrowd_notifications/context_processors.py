from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest
from notifications.models import Notification

from .views import app_channel_qs


def unread_notification_count(request: HttpRequest) -> dict[str, Any]:
    """Adds the unread in-app notification count for the header bell."""
    if not request.user.is_authenticated:
        return {}

    # notifications is untyped (see mypy.ini): user.notifications is invisible to mypy.
    qs: QuerySet[Notification] = app_channel_qs(request.user.notifications.all())  # type: ignore[attr-defined]
    return {"unread_count": qs.unread().count()}  # type: ignore[attr-defined]
